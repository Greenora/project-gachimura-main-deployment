#!/usr/bin/env python3
"""Back up the service database and uploaded images to an explicitly private S3 bucket."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlsplit


IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
PENDING_NAME = re.compile(r'pending-\d{8}T\d{6}Z-[0-9a-f]{8}\.tar\.gz')
PUBLIC_BLOCK_FIELDS = ('BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets')
STAGING_MARKER = '.gachimura-backup-owner'
STAGING_OWNER = b'gachimura-service-backup-staging-v1\n'


class BackupError(Exception):
    pass


def command(args, *, environment=None, output=None):
    return subprocess.run(
        args, env={**(os.environ if environment is None else environment),
                   'AWS_PAGER': '', 'AWS_CLI_AUTO_PROMPT': 'off'},
        stdout=output if output is not None else subprocess.PIPE,
        stderr=subprocess.PIPE, text=output is None, check=True, timeout=300,
    ).stdout


def destination_parts(destination):
    parsed = urlsplit(destination)
    if (parsed.scheme != 's3' or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]', parsed.netloc)
            or not parsed.path.strip('/')
            or parsed.query or parsed.fragment or any(part in ('.', '..') for part in parsed.path.split('/'))):
        raise BackupError('S3 버킷과 백업 경로를 확인해주세요.')
    return parsed.netloc, destination.rstrip('/') + '/'


def check_private_bucket(bucket):
    config = json.loads(command(['aws', 's3api', 'get-public-access-block', '--bucket', bucket]))
    if not all(config.get('PublicAccessBlockConfiguration', {}).get(field) is True for field in PUBLIC_BLOCK_FIELDS):
        raise BackupError('S3의 모든 퍼블릭 액세스 차단을 켠 뒤 재시도해주세요.')


def database_settings(project):
    config = json.loads(command([
        'docker', 'compose', '--env-file', str(project / '.env'), '-p', 'gachimura-base',
        '-f', str(project / 'docker-compose.base.yml'), 'config', '--format', 'json',
    ]))
    expected = config['volumes']['mysql_data']
    inspected = json.loads(command(['docker', 'inspect', 'gachimura-db']))[0]
    actual = next((item.get('Name') for item in inspected['Mounts'] if item['Destination'] == '/var/lib/mysql'), None)
    if expected.get('external') is not True or not actual or actual != expected.get('name'):
        raise BackupError('배포 설정과 실행 중인 DB 저장소를 확인해주세요.')
    values = dict(value.split('=', 1) for value in inspected['Config']['Env'] if '=' in value)
    database = values.get('MYSQL_DATABASE', '')
    user = values.get('MYSQL_USER') or 'root'
    password = values.get('MYSQL_ROOT_PASSWORD') if user == 'root' else values.get('MYSQL_PASSWORD')
    if not re.fullmatch(r'[A-Za-z0-9_]+', database) or not password:
        raise BackupError('실행 중인 DB의 백업 접속 설정을 확인해주세요.')
    return inspected['Id'], database, user, {**os.environ, 'MYSQL_PWD': password}


def image_files(uploads):
    if uploads.is_symlink() or not uploads.is_dir():
        raise BackupError('업로드 저장 폴더를 확인해주세요.')
    files = []
    for directory, directories, names in os.walk(uploads, followlinks=False):
        root = Path(directory)
        directories[:] = [name for name in directories if not name.startswith('.') and not (root / name).is_symlink()]
        for name in names:
            path = root / name
            if (not name.startswith(('.', 'receipt-')) and path.suffix.lower() in IMAGE_EXTENSIONS
                    and not path.is_symlink() and path.is_file()):
                files.append(path)
    return files


def upload(path, destination):
    if path.is_symlink() or not path.is_file() or path.stat().st_size == 0:
        raise BackupError('전송할 백업 파일을 확인해주세요.')
    command(['aws', 's3', 'cp', str(path), destination + path.name,
             '--sse', 'AES256', '--only-show-errors', '--no-progress'])
    path.unlink()
    print('비공개 S3 백업 전송 완료: ' + path.name, flush=True)


def archive_backup(project, folder):
    container, database, user, environment = database_settings(project)
    uploads = project.parent / 'gachimura-data' / 'uploads'
    files = image_files(uploads)
    database_size = int(command([
        'docker', 'exec', '--env', 'MYSQL_PWD', container, 'mysql',
        '--host=127.0.0.1', '--user=' + user, '--database=' + database,
        '--batch', '--skip-column-names',
        '--execute=SELECT 1 FROM users LIMIT 0; SELECT COALESCE(SUM(data_length + index_length), 0) FROM information_schema.tables WHERE table_schema=DATABASE()',
    ], environment=environment).strip())
    minimum_space = 256 * 1024 * 1024 + database_size * 3 + sum(path.stat().st_size for path in files) * 2
    if shutil.disk_usage(folder).free < minimum_space:
        raise BackupError('백업을 만들 서버 공간이 부족합니다.')
    with tempfile.TemporaryDirectory(prefix='.building-', dir=folder) as directory:
        staging = Path(directory)
        (staging / STAGING_MARKER).write_bytes(STAGING_OWNER)
        sql = staging / 'database.sql'
        with sql.open('xb') as stream:
            command([
                'docker', 'exec', '--env', 'MYSQL_PWD', container, 'mysqldump',
                '--host=127.0.0.1', '--user=' + user, '--single-transaction', '--quick',
                '--no-tablespaces', '--set-gtid-purged=OFF', '--databases', database,
            ], environment=environment, output=stream)
        if sql.stat().st_size == 0:
            raise BackupError('DB 백업 내용을 확인하지 못했습니다.')
        created = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        manifest = staging / 'manifest.json'
        digest = hashlib.sha256()
        with sql.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        manifest.write_text(json.dumps({'createdAtUtc': created, 'database': database,
                                       'sqlSha256': digest.hexdigest(), 'imageCount': len(files)}))
        archive = staging / 'backup.tar.gz'
        # shortcut: DB and uploads are separate snapshots; use versioned storage if images become deletable during backup.
        with tarfile.open(archive, 'w:gz', dereference=False) as package:
            package.add(sql, arcname='database.sql', recursive=False)
            package.add(manifest, arcname='manifest.json', recursive=False)
            for image in files:
                if image.is_symlink() or not image.is_file():
                    raise BackupError('백업 중 이미지가 변경됐습니다. 다시 시도해주세요.')
                package.add(image, arcname='uploads/' + image.relative_to(uploads).as_posix(), recursive=False)
        pending = folder / ('pending-' + created + '-' + secrets.token_hex(4) + '.tar.gz')
        archive.rename(pending)
        pending.chmod(0o600)
        return pending


def backup(project, destination):
    bucket, target = destination_parts(destination)
    for tool in ('docker', 'aws'):
        if shutil.which(tool) is None:
            raise BackupError(tool + ' CLI 설치를 확인해주세요.')
    os.umask(0o077)
    folder = project.parent / 'gachimura-data' / 'backups' / 'scheduled'
    if folder.is_symlink():
        raise BackupError('백업 작업 폴더를 확인해주세요.')
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    lock_path = folder / '.lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for staging in folder.glob('.building-*'):
            if staging.is_symlink() or not staging.is_dir():
                continue
            marker = staging / STAGING_MARKER
            if not marker.is_symlink() and marker.is_file() and marker.read_bytes() == STAGING_OWNER:
                shutil.rmtree(staging)
        check_private_bucket(bucket)
        # Retry the retained complete backup before creating another, so failed transfers do not accumulate.
        for pending in sorted(folder.iterdir()):
            if PENDING_NAME.fullmatch(pending.name):
                upload(pending, target)
        upload(archive_backup(project, folder), target)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', default=os.environ.get('BACKUP_S3_URI'))
    args = parser.parse_args()
    try:
        if not args.destination:
            raise BackupError('--destination 또는 BACKUP_S3_URI에 비공개 S3 경로를 지정해주세요.')
        backup(Path(__file__).resolve().parents[1], args.destination)
    except BlockingIOError:
        print('다른 백업 작업이 실행 중입니다. 잠시 후 다시 시도해주세요.')
        raise SystemExit(1)
    except BackupError as error:
        print(str(error))
        raise SystemExit(1)
    except (OSError, KeyError, IndexError, ValueError, subprocess.SubprocessError, tarfile.TarError):
        print('백업을 완료하지 못했습니다. DB·AWS CLI·S3 권한을 확인해주세요. 완성된 미전송 백업은 보존됩니다.')
        raise SystemExit(1)

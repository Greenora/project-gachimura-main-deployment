from pathlib import Path
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/backup-service.py'
SECRET = 'fixture-server-password-not-for-logs'
PRIVATE = 'fixture-private@example.test'

DOCKER = '''#!/usr/bin/env python3
import json,os,sys
args=sys.argv[1:]
with open(os.environ['CALL_LOG'],'a') as stream: stream.write(json.dumps(['docker',*args])+'\\n')
if args[0]=='compose' and args[-3:]==['config','--format','json']:
    print(json.dumps({'volumes':{'mysql_data':{'name':'fixture-data','external':True}}}))
elif args[0]=='inspect':
    print(json.dumps([{'Id':'fixture-database-id','Mounts':[{'Destination':'/var/lib/mysql','Name':'other' if os.environ.get('BAD_VOLUME') else 'fixture-data'}],
        'Config':{'Env':['MYSQL_DATABASE=gachimura','MYSQL_USER=fixture','MYSQL_PASSWORD='+os.environ['SECRET']]}}]))
elif args[0]=='exec':
    assert args[1:4]==['--env','MYSQL_PWD','fixture-database-id']
    assert os.environ.get('MYSQL_PWD')==os.environ['SECRET']
    if 'mysqldump' in args:
        for option in ['--single-transaction','--quick','--no-tablespaces','--set-gtid-purged=OFF']: assert option in args
        if os.environ.get('FAIL_DUMP'):
            print(os.environ['SECRET']+' '+os.environ['PRIVATE'],file=sys.stderr); sys.exit(1)
        print("CREATE DATABASE IF NOT EXISTS gachimura; USE gachimura; CREATE TABLE users(id INT, email VARCHAR(255)); INSERT INTO users VALUES(1,'"+os.environ['PRIVATE']+"');")
    elif 'mysql' in args:
        assert any('FROM users LIMIT 0' in arg for arg in args)
        print(1024)
    else: sys.exit(1)
else: sys.exit(1)
'''

AWS = '''#!/usr/bin/env python3
import json,os,shutil,sys
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['CALL_LOG'],'a') as stream: stream.write(json.dumps(['aws',*args])+'\\n')
if args[:2]==['s3api','get-public-access-block']:
    fields=['BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets']
    print(json.dumps({'PublicAccessBlockConfiguration':{field:not bool(os.environ.get('PUBLIC_BUCKET')) for field in fields}}))
elif args[:2]==['s3','cp']:
    assert args[4:]==['--sse','AES256','--only-show-errors','--no-progress']
    if os.environ.get('FAIL_UPLOAD'):
        print(os.environ['SECRET']+' '+os.environ['PRIVATE'],file=sys.stderr); sys.exit(1)
    shutil.copy2(args[2],Path(os.environ['CLOUD'])/args[3].split('/')[-1])
else: sys.exit(1)
'''


class ServiceBackupTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / 'project'
        (self.project / 'scripts').mkdir(parents=True)
        shutil.copy2(SCRIPT, self.project / 'scripts/backup-service.py')
        (self.project / '.env').write_text('PRIVATE_KEY=' + SECRET)
        (self.project / 'docker-compose.base.yml').write_text('fixture only')
        self.data = self.root / 'gachimura-data'
        self.uploads = self.data / 'uploads'
        self.uploads.mkdir(parents=True)
        (self.uploads / '123-456.png').write_bytes(b'fixture image')
        (self.uploads / 'legacy-profile.JPG').write_bytes(b'legacy fixture')
        (self.uploads / 'legacy').mkdir()
        (self.uploads / 'legacy/old-image.jpeg').write_bytes(b'old fixture')
        for filename in ['.env', 'service-account.json', 'private.key', 'receipt-123-9.png', '.hidden.jpg']:
            (self.uploads / filename).write_text(SECRET)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'private.jpg').write_text(SECRET)
        (self.uploads / 'external.jpg').symlink_to(outside / 'private.jpg')
        (self.uploads / 'linked').symlink_to(outside, target_is_directory=True)
        self.backups = self.data / 'backups'
        self.backups.mkdir()
        (self.backups / 'manual-before-recovery.sql').write_text('keep original backup')
        self.scheduled = self.backups / 'scheduled'
        self.commands = self.root / 'bin'
        self.commands.mkdir()
        for name, source in [('docker', DOCKER), ('aws', AWS)]:
            path = self.commands / name
            path.write_text(source)
            path.chmod(0o700)
        self.cloud = self.root / 'cloud'
        self.cloud.mkdir()
        self.log = self.root / 'calls'
        self.environment = {**os.environ, 'PATH': str(self.commands) + ':' + os.environ['PATH'],
                            'SECRET': SECRET, 'PRIVATE': PRIVATE, 'CLOUD': str(self.cloud),
                            'CALL_LOG': str(self.log)}
        self.environment.pop('BACKUP_S3_URI', None)

    def run_backup(self, destination='s3://fixture-private-bucket/daily/', **environment):
        result = subprocess.run(
            [sys.executable, str(self.project / 'scripts/backup-service.py'), '--destination', destination],
            env={**self.environment, **environment}, capture_output=True, text=True, timeout=20,
        )
        self.assertNotIn(SECRET, result.stdout + result.stderr)
        self.assertNotIn(PRIVATE, result.stdout + result.stderr)
        self.assertEqual((self.backups / 'manual-before-recovery.sql').read_text(), 'keep original backup')
        self.assertEqual((self.uploads / '123-456.png').read_bytes(), b'fixture image')
        return result

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_private_backup_contains_database_and_legacy_images_but_never_environment_keys_or_receipts(self):
        result = self.run_backup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archives = list(self.cloud.glob('*.tar.gz'))
        self.assertEqual(len(archives), 1)
        with tarfile.open(archives[0]) as archive:
            self.assertEqual(set(archive.getnames()), {
                'database.sql', 'manifest.json', 'uploads/123-456.png',
                'uploads/legacy-profile.JPG', 'uploads/legacy/old-image.jpeg',
            })
            sql = archive.extractfile('database.sql').read()
            manifest = json.load(archive.extractfile('manifest.json'))
            self.assertIn(PRIVATE.encode(), sql)
            self.assertNotIn(SECRET.encode(), sql)
            self.assertEqual(manifest['sqlSha256'], hashlib.sha256(sql).hexdigest())
            self.assertEqual(manifest['imageCount'], 3)
            self.assertTrue(all(not item.issym() and not item.islnk() for item in archive.getmembers()))
        self.assertEqual(self.scheduled.stat().st_mode & 0o777, 0o700)
        self.assertEqual(archives[0].stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(self.scheduled.glob('*.tar.gz')), [])
        self.assertNotIn(SECRET, self.log.read_text())
        self.assertFalse(any(call[1] in ('stop', 'rm', 'restart') for call in self.calls()))

    def test_failed_transfer_retains_one_complete_backup_and_retries_it_before_creating_another(self):
        self.assertNotEqual(self.run_backup(FAIL_UPLOAD='1').returncode, 0)
        pending = list(self.scheduled.glob('*.tar.gz'))
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].stat().st_mode & 0o777, 0o600)
        self.assertNotEqual(self.run_backup(FAIL_UPLOAD='1').returncode, 0)
        self.assertEqual(list(self.scheduled.glob('*.tar.gz')), pending)
        self.assertEqual(sum('mysqldump' in call for call in self.calls()), 1)
        self.assertEqual(self.run_backup().returncode, 0)
        self.assertEqual(len(list(self.cloud.glob('*.tar.gz'))), 2)
        self.assertEqual(sum('mysqldump' in call for call in self.calls()), 2)
        self.assertFalse(pending[0].exists())

    def test_public_bucket_is_rejected_before_database_reads(self):
        result = self.run_backup(PUBLIC_BUCKET='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('퍼블릭 액세스 차단', result.stdout)
        self.assertFalse(any(call[0] == 'docker' for call in self.calls()))

    def test_wrong_database_volume_is_rejected_without_a_dump(self):
        self.assertNotEqual(self.run_backup(BAD_VOLUME='1').returncode, 0)
        self.assertFalse(any('mysqldump' in call for call in self.calls()))
        self.assertEqual(list(self.cloud.iterdir()), [])

    def test_dump_errors_are_redacted_and_partial_files_are_not_published(self):
        self.assertNotEqual(self.run_backup(FAIL_DUMP='1').returncode, 0)
        self.assertEqual(list(self.cloud.iterdir()), [])
        self.assertEqual([path for path in self.scheduled.iterdir() if path.name != '.lock'], [])

    def test_concurrent_job_is_rejected_before_cloud_or_database_work(self):
        self.scheduled.mkdir(mode=0o700)
        with (self.scheduled / '.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_backup()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('다른 백업 작업', result.stdout)
        self.assertEqual(self.calls(), [])

    def test_unknown_manual_files_and_symlink_pending_files_are_not_removed(self):
        self.scheduled.mkdir(mode=0o700)
        manual = self.scheduled / 'pending-manual-backup.tar.gz'
        manual.write_text('manual backup')
        self.assertEqual(self.run_backup().returncode, 0)
        self.assertEqual(manual.read_text(), 'manual backup')
        bad = self.scheduled / 'pending-20261123T000000Z-12345678.tar.gz'
        bad.symlink_to(self.backups / 'manual-before-recovery.sql')
        self.assertNotEqual(self.run_backup().returncode, 0)
        self.assertTrue(bad.is_symlink())

    def test_interrupted_staging_cleanup_requires_our_marker_and_never_follows_symlinks(self):
        self.scheduled.mkdir(mode=0o700)
        marker_name = '.gachimura-backup-owner'
        owner = b'gachimura-service-backup-staging-v1\n'
        owned = self.scheduled / '.building-interrupted'
        owned.mkdir()
        (owned / marker_name).write_bytes(owner)
        (owned / 'database.sql').write_text(PRIVATE)
        (owned / 'manual-link').symlink_to(self.backups / 'manual-before-recovery.sql')
        preserved = []
        for name, marker in [('.building-manual', b'manual owner'), ('.building-unmarked', None), ('manual-directory', owner)]:
            directory = self.scheduled / name
            directory.mkdir()
            if marker is not None:
                (directory / marker_name).write_bytes(marker)
            (directory / 'keep').write_text('preserve')
            preserved.append(directory)
        external = self.root / 'external-staging'
        external.mkdir()
        (external / marker_name).write_bytes(owner)
        (external / 'keep').write_text('preserve external')
        linked = self.scheduled / '.building-symlink'
        linked.symlink_to(external, target_is_directory=True)
        false_owner = self.scheduled / '.building-marker-symlink'
        false_owner.mkdir()
        (false_owner / marker_name).symlink_to(external / marker_name)
        with (self.scheduled / '.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertNotEqual(self.run_backup().returncode, 0)
            self.assertTrue(owned.exists())
        result = self.run_backup()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(owned.exists())
        self.assertTrue(linked.is_symlink())
        self.assertTrue((false_owner / marker_name).is_symlink())
        self.assertEqual((external / 'keep').read_text(), 'preserve external')
        for directory in preserved:
            self.assertEqual((directory / 'keep').read_text(), 'preserve')

    def test_invalid_destinations_and_missing_cli_fail_before_data_work(self):
        for destination in ['https://example.test/', 's3://fixture-private-bucket/', 's3://fixture-private-bucket/daily/../other', 's3://fixture-private-bucket/?secret=value']:
            with self.subTest(destination=destination):
                self.assertNotEqual(self.run_backup(destination).returncode, 0)
        (self.commands / 'aws').unlink()
        result = self.run_backup(PATH=str(self.commands))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('aws CLI', result.stdout)
        self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()

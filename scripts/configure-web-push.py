"""Prepare persistent Web Push keys in the server .env without printing them."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile


FIELDS = ('WEB_PUSH_PUBLIC_KEY', 'WEB_PUSH_PRIVATE_KEY', 'WEB_PUSH_SUBJECT')
KEY_SCRIPT = r'''
const fs = require('node:fs');
const { createECDH } = require('node:crypto');
try {
  const input = JSON.parse(fs.readFileSync(0, 'utf8'));
  const publicKey = input.WEB_PUSH_PUBLIC_KEY || '';
  const privateKey = input.WEB_PUSH_PRIVATE_KEY || '';
  const subject = input.WEB_PUSH_SUBJECT || 'https://gachimura.com';
  const contact = new URL(subject);
  if (!['https:', 'mailto:'].includes(contact.protocol) || contact.username || contact.password ||
      (contact.protocol === 'mailto:' && !/^[^\s@]+@[^\s@]+$/.test(contact.pathname))) throw 0;
  if (Boolean(publicKey) !== Boolean(privateKey)) throw 0;
  const ecdh = createECDH('prime256v1');
  if (privateKey) {
    if (!/^[A-Za-z0-9_-]{43}$/.test(privateKey) || !/^[A-Za-z0-9_-]{87}$/.test(publicKey)) throw 0;
    ecdh.setPrivateKey(Buffer.from(privateKey, 'base64url'));
    if (ecdh.getPublicKey().toString('base64url') !== publicKey) throw 0;
  } else {
    ecdh.generateKeys();
  }
  const privateBytes = ecdh.getPrivateKey();
  const paddedPrivateKey = Buffer.alloc(32);
  privateBytes.copy(paddedPrivateKey, 32 - privateBytes.length);
  process.stdout.write(JSON.stringify({
    WEB_PUSH_PUBLIC_KEY: ecdh.getPublicKey().toString('base64url'),
    WEB_PUSH_PRIVATE_KEY: paddedPrivateKey.toString('base64url'),
    WEB_PUSH_SUBJECT: subject,
  }));
} catch {
  process.exitCode = 1;
}
'''


def settings(text):
    values = {}
    for line in text.splitlines():
        candidate = re.sub(r'^export\s+', '', line.strip())
        name, separator, value = candidate.partition('=')
        name = name.strip()
        if name not in FIELDS:
            continue
        if not separator or name in values:
            raise ValueError('푸시 설정이 중복되거나 잘못되어 있습니다. 기존 값은 변경하지 않았습니다.')
        value = value.strip()
        if value[:1] in ('"', "'"):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError('푸시 설정의 따옴표를 확인해주세요. 기존 값은 변경하지 않았습니다.')
            value = value[1:-1]
        else:
            value = value.split(' #', 1)[0].strip()
        values[name] = value
    return values


def configure(root):
    env_file = root / '.env'
    original = env_file.read_bytes()
    text = original.decode('utf-8')
    existing = settings(text)
    result = subprocess.run(
        ['docker', 'compose', '--env-file', '.env', '-f', 'docker-compose.prod.yml',
         'exec', '-T', 'backend', 'node', '-e', KEY_SCRIPT],
        input=json.dumps(existing), cwd=root, capture_output=True, text=True, timeout=30,
    )
    if result.returncode:
        raise RuntimeError('키 확인·생성에 실패했습니다. 백엔드 실행 상태와 기존 푸시 키 쌍을 확인해주세요. 키는 변경하지 않았습니다.')
    generated = json.loads(result.stdout)
    if set(generated) != set(FIELDS) or not all(isinstance(generated[key], str) and generated[key] for key in FIELDS):
        raise ValueError('키 생성 결과를 확인하지 못했습니다. 기존 값은 변경하지 않았습니다.')
    if env_file.read_bytes() != original:
        raise ValueError('환경 파일이 실행 중 변경되었습니다. 다시 실행해주세요.')
    if existing == generated:
        os.chmod(env_file, 0o600)
        print('기존 푸시 키 쌍: 정상, 재생성하지 않음')
        return
    backup = root.parent / 'gachimura-data' / 'backups' / (
        'before-web-push-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-') + secrets.token_hex(4)
    )
    backup.mkdir(parents=True, mode=0o700)
    backup_file = backup / '.env'
    with os.fdopen(os.open(backup_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(original)
    newline = '\r\n' if '\r\n' in text else '\n'
    remaining = [line for line in text.splitlines() if not re.match(
        r'^\s*(?:export\s+)?(?:' + '|'.join(FIELDS) + r')\s*=', line
    )]
    updated = newline.join(remaining).rstrip('\r\n') + newline
    updated += newline.join(f'{name}={generated[name]}' for name in FIELDS) + newline
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', newline='', dir=root, prefix='.env.web-push-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        if env_file.read_bytes() != original:
            raise ValueError('환경 파일이 실행 중 변경되었습니다. 다시 실행해주세요.')
        os.replace(temporary, env_file)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print('기존 환경 파일 백업 완료: ' + str(backup))
    for name in FIELDS:
        print(name + ': 설정됨')
    print('적용은 다음 백엔드 배포에서 진행됩니다.')


if __name__ == '__main__':
    try:
        configure(Path.cwd())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        print('푸시 설정을 완료하지 못했습니다. 백엔드 실행 상태와 환경 파일의 푸시 설정을 확인해주세요.')
        raise SystemExit(1)

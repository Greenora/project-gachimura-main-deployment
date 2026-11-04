from contextlib import redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/configure-web-push.py'
SPEC = importlib.util.spec_from_file_location('push_setup', SCRIPT)
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)
REAL_RUN = subprocess.run


class PushSetupTest(unittest.TestCase):
    def node(self, command, **kwargs):
        self.assertNotIn('WEB_PUSH_PRIVATE_KEY=', ' '.join(command))
        return REAL_RUN(['node', '-e', setup.KEY_SCRIPT], input=kwargs['input'], capture_output=True, text=True, check=False)

    def run_setup(self, root):
        output = io.StringIO()
        with patch.object(setup.subprocess, 'run', side_effect=self.node), redirect_stdout(output):
            setup.configure(root)
        return output.getvalue()

    def test_generation_reuse_backup_permissions_and_no_secret_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'project'
            root.mkdir()
            env = root / '.env'
            original = 'SMTP_PASS=PRIVATE_FIXTURE\nGOOGLE_VISION_CREDENTIALS_BASE64=OCR_FIXTURE\n'
            env.write_text(original)
            output = self.run_setup(root)
            saved = env.read_text()
            values = setup.settings(saved)
            self.assertEqual(len(values['WEB_PUSH_PRIVATE_KEY']), 43)
            self.assertEqual(len(values['WEB_PUSH_PUBLIC_KEY']), 87)
            self.assertTrue(saved.startswith(original))
            self.assertEqual(os.stat(env).st_mode & 0o777, 0o600)
            backups = list((Path(directory) / 'gachimura-data/backups').glob('*/.env'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), original)
            self.assertEqual(os.stat(backups[0]).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(backups[0].parent).st_mode & 0o777, 0o700)
            self.assertNotIn(values['WEB_PUSH_PRIVATE_KEY'], output)
            self.assertNotIn('PRIVATE_FIXTURE', output)
            os.chmod(env, 0o644)
            output = self.run_setup(root)
            self.assertEqual(env.read_text(), saved)
            self.assertEqual(os.stat(env).st_mode & 0o777, 0o600)
            self.assertIn('재생성하지 않음', output)
            self.assertEqual(len(list(backups[0].parent.parent.glob('*/.env'))), 1)

    def test_incomplete_or_invalid_keys_leave_environment_unchanged(self):
        for value in ['WEB_PUSH_PUBLIC_KEY=incomplete\n', 'WEB_PUSH_PUBLIC_KEY=bad\nWEB_PUSH_PRIVATE_KEY=bad\n']:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / '.env').write_text(value)
                with self.assertRaises(RuntimeError):
                    self.run_setup(root)
                self.assertEqual((root / '.env').read_text(), value)

    def test_duplicate_entries_are_not_silently_overwritten(self):
        with self.assertRaises(ValueError):
            setup.settings('WEB_PUSH_PUBLIC_KEY=first\nWEB_PUSH_PUBLIC_KEY=second\n')

    def test_contact_validation_matches_backend(self):
        for subject in ['mailto:not-an-email', 'mailto:user@', 'https://user:pass@example.test']:
            with self.subTest(subject=subject), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                original = 'WEB_PUSH_SUBJECT=' + subject + '\n'
                (root / '.env').write_text(original)
                with self.assertRaises(RuntimeError):
                    self.run_setup(root)
                self.assertEqual((root / '.env').read_text(), original)
        result = self.node([], input=json.dumps({'WEB_PUSH_SUBJECT': 'mailto:admin@example.test'}))
        self.assertEqual(result.returncode, 0)

    def test_quoted_values_and_crlf_are_supported(self):
        values = setup.settings('export WEB_PUSH_PUBLIC_KEY="fixture"\r\nWEB_PUSH_SUBJECT=\'https://gachimura.com\'\r\n')
        self.assertEqual(values['WEB_PUSH_PUBLIC_KEY'], 'fixture')
        self.assertEqual(values['WEB_PUSH_SUBJECT'], 'https://gachimura.com')

    def test_leading_zero_private_keys_remain_32_bytes_and_are_reused(self):
        result = REAL_RUN(['node', '-e', "const c=require('node:crypto').createECDH('prime256v1');const p=Buffer.alloc(32);p[31]=1;c.setPrivateKey(p);process.stdout.write(JSON.stringify({WEB_PUSH_PUBLIC_KEY:c.getPublicKey().toString('base64url'),WEB_PUSH_PRIVATE_KEY:p.toString('base64url'),WEB_PUSH_SUBJECT:'https://gachimura.com'}));"], capture_output=True, text=True, check=True)
        values = json.loads(result.stdout)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = ''.join(f'{name}={values[name]}\n' for name in setup.FIELDS)
            (root / '.env').write_text(original)
            output = self.run_setup(root)
            self.assertEqual((root / '.env').read_text(), original)
            self.assertIn('재생성하지 않음', output)
            self.assertNotIn(values['WEB_PUSH_PRIVATE_KEY'], output)

    def test_concurrent_environment_edit_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = root / '.env'
            env.write_text('SMTP_PASS=before\n')
            def concurrent(command, **kwargs):
                result = self.node(command, **kwargs)
                env.write_text('SMTP_PASS=concurrent-change\n')
                return result
            with patch.object(setup.subprocess, 'run', side_effect=concurrent), self.assertRaises(ValueError):
                setup.configure(root)
            self.assertEqual(env.read_text(), 'SMTP_PASS=concurrent-change\n')


if __name__ == '__main__':
    unittest.main()

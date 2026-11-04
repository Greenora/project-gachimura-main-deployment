import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class WebPushConfigTest(unittest.TestCase):
    def services(self, values=None):
        keys = ('WEB_PUSH_PUBLIC_KEY', 'WEB_PUSH_PRIVATE_KEY', 'WEB_PUSH_SUBJECT')
        environment = {key: value for key, value in os.environ.items() if key not in keys}
        environment.update(values or {})
        compose = Path(__file__).resolve().parents[1] / 'docker-compose.prod.yml'
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'compose.yml'
            config.write_text(compose.read_text())
            result = subprocess.run(['docker', 'compose', '--env-file', '/dev/null', '-f', str(config), 'config', '--format', 'json'], env=environment, capture_output=True, text=True, check=True)
        return json.loads(result.stdout)['services']

    def test_unconfigured_push_is_disabled_without_secrets(self):
        services = self.services()
        backend = services['backend']['environment']
        self.assertEqual(backend['WEB_PUSH_PUBLIC_KEY'], '')
        self.assertEqual(backend['WEB_PUSH_PRIVATE_KEY'], '')
        self.assertEqual(backend['WEB_PUSH_SUBJECT'], 'https://gachimura.com')

    def test_push_keys_only_reach_backend_runtime(self):
        values = {'WEB_PUSH_PUBLIC_KEY': 'PUBLIC_FIXTURE', 'WEB_PUSH_PRIVATE_KEY': 'PRIVATE_FIXTURE', 'WEB_PUSH_SUBJECT': 'mailto:fixture@example.test'}
        services = self.services(values)
        for key, value in values.items():
            self.assertEqual(services['backend']['environment'][key], value)
            self.assertNotIn(key, json.dumps(services['frontend']))
            self.assertNotIn(key, json.dumps(services['backend']['build']))


if __name__ == '__main__':
    unittest.main()

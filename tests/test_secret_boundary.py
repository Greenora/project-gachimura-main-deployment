import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


class SecretBoundaryTest(unittest.TestCase):
    def test_private_credentials_are_not_forwarded_to_frontend_or_builds(self):
        root = Path(__file__).resolve().parents[1]
        for color in ('prod', 'blue', 'green'):
            with self.subTest(environment=color):
                suffix = '' if color == 'prod' else '-' + color
                self.check_services(root / f'docker-compose.{color}.yml', suffix)

    def check_services(self, compose, suffix):
        source = compose.read_text()
        names = set(re.findall(r'\$\{([A-Z][A-Z0-9_]*)', source))
        environment = {key: value for key, value in os.environ.items() if key not in names}
        values = {
            'NEXT_PUBLIC_KAKAO_CLIENT_SECRET': 'PRIVATE_FRONTEND_FIXTURE',
            'KAKAO_CLIENT_SECRET': 'PRIVATE_SERVER_FIXTURE',
            'LINE_CHANNEL_SECRET': 'PRIVATE_LINE_FIXTURE',
            'JWT_SECRET': 'FIXTURE_JWT_SECRET_WITH_AT_LEAST_32_CHARACTERS',
            'SMTP_PASS': 'PRIVATE_SMTP_FIXTURE',
            'WEB_PUSH_PRIVATE_KEY': 'PRIVATE_PUSH_FIXTURE',
            'GOOGLE_VISION_CREDENTIALS_BASE64': 'PRIVATE_VISION_FIXTURE',
        }
        environment.update(values)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'compose.yml'
            config.write_text(source)
            result = subprocess.run(
                ['docker', 'compose', '--env-file', '/dev/null', '-f', str(config), 'config', '--format', 'json'],
                env=environment, capture_output=True, text=True, check=True,
            )
        services = json.loads(result.stdout)['services']
        frontend = json.dumps(services['frontend' + suffix])
        builds = json.dumps([value.get('build', {}) for value in services.values()])
        for name, value in values.items():
            self.assertNotIn(value, frontend, name)
            self.assertNotIn(value, builds, name)
            if name != 'NEXT_PUBLIC_KAKAO_CLIENT_SECRET':
                self.assertEqual(services['backend' + suffix]['environment'][name], value)


if __name__ == '__main__':
    unittest.main()

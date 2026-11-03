import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class OcrCredentialsConfigTest(unittest.TestCase):
    def rendered_services(self, credentials=None):
        compose = Path(__file__).resolve().parents[1] / 'docker-compose.prod.yml'
        environment = dict(os.environ)
        environment.pop('GOOGLE_VISION_CREDENTIALS_BASE64', None)
        if credentials is not None:
            environment['GOOGLE_VISION_CREDENTIALS_BASE64'] = credentials
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'compose.yml'
            config.write_text(compose.read_text())
            result = subprocess.run(
                ['docker', 'compose', '--env-file', '/dev/null', '-f', str(config),
                 'config', '--format', 'json'],
                env=environment, capture_output=True, text=True, check=True,
            )
        return json.loads(result.stdout)['services']

    def test_credentials_are_optional_before_ocr_setup(self):
        services = self.rendered_services()
        self.assertEqual(
            services['backend']['environment']['GOOGLE_VISION_CREDENTIALS_BASE64'],
            '',
        )

    def test_credentials_reach_only_the_backend_at_runtime(self):
        credentials = base64.b64encode(json.dumps({
            'project_id': 'fixture-project',
            'client_email': 'fixture@example.test',
            'private_key': 'fixture-only-not-a-real-key',
        }).encode()).decode()
        services = self.rendered_services(credentials)
        self.assertEqual(
            services['backend']['environment']['GOOGLE_VISION_CREDENTIALS_BASE64'],
            credentials,
        )
        self.assertNotIn(credentials, json.dumps(services['frontend']))
        self.assertNotIn(credentials, json.dumps(services['backend']['build']))


if __name__ == '__main__':
    unittest.main()

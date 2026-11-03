import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class ChatOriginConfigTest(unittest.TestCase):
    def rendered_backend(self, override=None):
        compose = Path(__file__).resolve().parents[1] / 'docker-compose.prod.yml'
        environment = dict(os.environ)
        environment.pop('CORS_ORIGINS', None)
        if override is not None:
            environment['CORS_ORIGINS'] = override
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'compose.yml'
            config.write_text(compose.read_text())
            result = subprocess.run(
                ['docker', 'compose', '--env-file', '/dev/null', '-f', str(config),
                 'config', '--format', 'json'],
                env=environment, capture_output=True, text=True, check=True,
            )
        return json.loads(result.stdout)['services']['backend']['environment']

    def test_production_domain_is_allowed_without_extra_env_setup(self):
        backend = self.rendered_backend()
        self.assertEqual(backend['CORS_ORIGINS'], 'https://gachimura.com')

    def test_explicit_allowlist_is_preserved(self):
        origins = 'https://gachimura.com,http://localhost:3101'
        self.assertEqual(self.rendered_backend(origins)['CORS_ORIGINS'], origins)


if __name__ == '__main__':
    unittest.main()

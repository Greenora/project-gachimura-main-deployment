import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LoggingConfigTest(unittest.TestCase):
    def test_all_production_services_have_bounded_container_logs(self):
        for environment in ('base', 'blue', 'green', 'prod'):
            with self.subTest(environment=environment), tempfile.TemporaryDirectory() as directory:
                config = Path(directory) / 'compose.yml'
                config.write_text((ROOT / f'docker-compose.{environment}.yml').read_text())
                result = subprocess.run(
                    ['docker', 'compose', '--env-file', '/dev/null', '-f', str(config), 'config', '--format', 'json'],
                    env={**os.environ, 'MYSQL_DATA_VOLUME': 'fixture-existing-data'},
                    capture_output=True, text=True, check=True,
                )
                services = json.loads(result.stdout)['services']
                for name, service in services.items():
                    self.assertEqual(service['logging'], {
                        'driver': 'json-file',
                        'options': {'max-size': '10m', 'max-file': '3'},
                    }, name)

    def test_nginx_uses_the_same_bounded_container_log_stream(self):
        config = (ROOT / 'nginx/nginx.conf').read_text()
        self.assertIn('access_log /dev/stdout main;', config)
        self.assertIn('error_log /dev/stderr warn;', config)
        self.assertNotIn('access_log /var/log/', config)
        self.assertNotIn('error_log /var/log/', config)


if __name__ == '__main__':
    unittest.main()

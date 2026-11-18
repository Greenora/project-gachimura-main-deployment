from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class BlueGreenSafetyTest(unittest.TestCase):
    def deploy(self, current='blue', healthy=True, reload_ok=True, legacy=False, inspect_ok=True, config_ok=True,
               target_volume='fixture-production-data', current_volume='fixture-production-data',
               volume_exists=True, database_exists=True, database_inspect_ok=True):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts').mkdir()
            (root / 'nginx/conf.d').mkdir(parents=True)
            script = root / 'scripts/deploy.sh'
            script.write_text((ROOT / 'scripts/deploy.sh').read_text())
            active = root / 'nginx/conf.d/active-env.inc'
            active.write_text('set $backend_upstream http://gachimura-backend-blue:3000;\n')
            commands = root / 'bin'
            commands.mkdir()
            docker = commands / 'docker'
            docker.write_text('''#!/bin/sh
printf '%s\n' "$*" >> "$TEST_CALL_LOG"
case "$1" in
  inspect)
    case "$2" in
      fixture-database-id)
        [ "$TEST_DATABASE_INSPECT_OK" = 1 ] || exit 1
        printf '%s\\n' "$TEST_CURRENT_VOLUME" ;;
      *) [ "$TEST_LEGACY" = 1 ]; exit $? ;;
    esac ;;
  volume) [ "$TEST_VOLUME_EXISTS" = 1 ]; exit $? ;;
  ps)
    [ "$TEST_INSPECT_OK" = 1 ] || exit 1
    case "$*" in
      *gachimura-db*)
        [ "$TEST_DATABASE_EXISTS" = 1 ] && printf 'fixture-database-id\\n'
        exit 0 ;;
      *backend-blue*) [ "$TEST_CURRENT" = blue ] || [ "$TEST_CURRENT" = both ] || exit 0 ;;
      *backend-green*) [ "$TEST_CURRENT" = green ] || [ "$TEST_CURRENT" = both ] || exit 0 ;;
    esac
    printf 'fixture-id\n' ;;
  compose)
    case "$*" in
      *'config --format json'*)
        printf '{"volumes":{"mysql_data":{"name":"%s","external":true}}}\\n' "$TEST_TARGET_VOLUME"
        exit 0 ;;
    esac
    case "$*" in
      *gachimura-base*) cat nginx/conf.d/active-env.inc > "$TEST_BASE_UPSTREAM" ;;
    esac
    case "$*" in
      *'run --rm --no-deps nginx nginx -t'*) [ "$TEST_CONFIG_OK" = 1 ] || exit 1 ;;
    esac ;;
  exec)
    case "$*" in
      *'nginx -s reload'*) [ "$TEST_RELOAD_OK" = 1 ] || exit 1 ;;
    esac ;;
esac
''')
            (commands / 'curl').write_text('#!/bin/sh\nif [ "$TEST_HEALTHY" = 1 ]; then printf 200; else printf 503; fi\n')
            (commands / 'sleep').write_text('#!/bin/sh\nexit 0\n')
            for executable in commands.iterdir():
                executable.chmod(0o700)
            result = subprocess.run(
                ['bash', str(script)], capture_output=True, text=True, timeout=10,
                env={**os.environ, 'PATH': str(commands) + ':' + os.environ['PATH'],
                     'TEST_CURRENT': current, 'TEST_HEALTHY': str(int(healthy)),
                     'TEST_RELOAD_OK': str(int(reload_ok)), 'TEST_LEGACY': str(int(legacy)),
                     'TEST_INSPECT_OK': str(int(inspect_ok)),
                     'TEST_CONFIG_OK': str(int(config_ok)),
                     'TEST_TARGET_VOLUME': target_volume, 'TEST_CURRENT_VOLUME': current_volume,
                     'TEST_VOLUME_EXISTS': str(int(volume_exists)),
                     'TEST_DATABASE_EXISTS': str(int(database_exists)),
                     'TEST_DATABASE_INSPECT_OK': str(int(database_inspect_ok)),
                     'TEST_CALL_LOG': str(root / 'calls'), 'TEST_BASE_UPSTREAM': str(root / 'base')},
            )
            calls = (root / 'calls').read_text().splitlines()
            base = (root / 'base').read_text() if (root / 'base').exists() else ''
            return result.returncode, calls, active.read_text(), base

    def test_green_stays_active_while_building_blue_after_git_reset(self):
        status, calls, active, base = self.deploy(current='green')
        self.assertEqual(status, 0)
        self.assertIn('gachimura-backend-green:3000', base)
        self.assertIn('gachimura-frontend-green:3000', base)
        self.assertIn('gachimura-backend-blue:3000', active)
        candidate = 'compose -p gachimura-base -f docker-compose.base.yml run --rm --no-deps nginx nginx -t'
        start = 'compose -p gachimura-base -f docker-compose.base.yml up -d'
        self.assertIn('compose -p gachimura-base -f docker-compose.base.yml build nginx', calls)
        self.assertLess(calls.index(candidate), calls.index(start))
        self.assertIn('exec gachimura-nginx nginx -t', calls)
        self.assertIn('compose -p gachimura-green -f docker-compose.green.yml down', calls)
        self.assertFalse(any(call.startswith(('stop ', 'rm ')) for call in calls))

    def test_failed_health_check_keeps_current_environment(self):
        status, calls, active, _ = self.deploy(healthy=False)
        self.assertNotEqual(status, 0)
        self.assertIn('gachimura-backend-blue:3000', active)
        self.assertIn('compose -p gachimura-green -f docker-compose.green.yml down', calls)
        self.assertNotIn('compose -p gachimura-blue -f docker-compose.blue.yml down', calls)
        self.assertFalse(any(call.startswith('exec ') for call in calls))

    def test_bad_candidate_proxy_config_never_replaces_running_services(self):
        status, calls, active, _ = self.deploy(config_ok=False)
        self.assertNotEqual(status, 0)
        self.assertIn('gachimura-backend-blue:3000', active)
        self.assertFalse(any(' up ' in call or call.endswith(' down') for call in calls))

    def test_failed_proxy_reload_restores_file_without_stopping_either_environment(self):
        status, calls, active, _ = self.deploy(reload_ok=False)
        self.assertNotEqual(status, 0)
        self.assertIn('gachimura-backend-blue:3000', active)
        self.assertFalse(any(call.endswith(' down') for call in calls))

    def test_ambiguous_or_legacy_environment_stops_before_any_container_changes(self):
        for values in ({'current': 'both'}, {'legacy': True}, {'inspect_ok': False}):
            with self.subTest(values=values):
                status, calls, _, _ = self.deploy(**values)
                self.assertNotEqual(status, 0)
                self.assertFalse(any(call.startswith(('compose ', 'exec ', 'stop ', 'rm ')) for call in calls))

    def test_database_requires_an_explicit_existing_volume(self):
        environment = {key: value for key, value in os.environ.items() if key != 'MYSQL_DATA_VOLUME'}
        command = ['docker', 'compose', '--env-file', '/dev/null', '-f', str(ROOT / 'docker-compose.base.yml'), 'config', '--format', 'json']
        missing = subprocess.run(command, env=environment, capture_output=True, text=True)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn('MYSQL_DATA_VOLUME', missing.stderr)
        environment['MYSQL_DATA_VOLUME'] = 'fixture-existing-production-data'
        result = subprocess.run(command, env=environment, capture_output=True, text=True, check=True)
        config = json.loads(result.stdout)
        self.assertEqual(config['volumes']['mysql_data']['name'], environment['MYSQL_DATA_VOLUME'])
        self.assertTrue(config['volumes']['mysql_data']['external'])

    def test_different_or_missing_database_volume_stops_before_service_changes(self):
        for values in ({'current_volume': 'fixture-other-data'}, {'volume_exists': False},
                       {'database_inspect_ok': False}):
            with self.subTest(values=values):
                status, calls, active, _ = self.deploy(current='green', **values)
                self.assertNotEqual(status, 0)
                self.assertIn('gachimura-backend-blue:3000', active)
                self.assertFalse(any(' build ' in call or ' up ' in call or ' run ' in call
                                     or call.endswith(' down') or call.startswith('exec ') for call in calls))

    def test_first_connection_uses_an_existing_external_volume(self):
        status, calls, active, _ = self.deploy(current='none', database_exists=False)
        self.assertEqual(status, 0)
        self.assertIn('volume inspect fixture-production-data', calls)
        self.assertIn('gachimura-backend-blue:3000', active)


if __name__ == '__main__':
    unittest.main()

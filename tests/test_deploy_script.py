from pathlib import Path
import os
import subprocess
import tempfile
import unittest


class DeploymentScriptTest(unittest.TestCase):
    def run_deployment(self, fetch_status=0, reset_status=0):
        workflow = Path(__file__).resolve().parents[1] / '.github/workflows/cd-develop.yml'
        lines = workflow.read_text().splitlines()
        start = lines.index('          script: |') + 1
        script = []
        for line in lines[start:]:
            if line.strip() and not line.startswith('            '):
                break
            script.append(line[12:])
        commit = 'a' * 40
        script = '\n'.join(script).replace('${{ github.sha }}', commit)
        stubs = '''
cd() { return 0; }
git() {
  printf 'git %s\\n' "$*" >> "$TEST_CALL_LOG"
  if [ "$1" = fetch ]; then return "$TEST_FETCH_STATUS"; fi
  if [ "$1" = reset ]; then
    if [ "$TEST_RESET_STATUS" -ne 0 ]; then return "$TEST_RESET_STATUS"; fi
    printf '%s\\n' "$3" > "$TEST_DEPLOYED_COMMIT"
  fi
  return 0
}
docker() { printf 'docker %s\\n' "$*" >> "$TEST_CALL_LOG"; }
'''
        with tempfile.TemporaryDirectory() as directory:
            calls_path = Path(directory) / 'calls'
            commit_path = Path(directory) / 'commit'
            result = subprocess.run(
                ['sh', '-c', stubs + '\n' + script],
                cwd=directory, capture_output=True, text=True,
                env={**os.environ, 'TEST_CALL_LOG': str(calls_path),
                     'TEST_DEPLOYED_COMMIT': str(commit_path),
                     'TEST_FETCH_STATUS': str(fetch_status),
                     'TEST_RESET_STATUS': str(reset_status)},
            )
            calls = calls_path.read_text().splitlines() if calls_path.exists() else []
            deployed = commit_path.read_text().strip() if commit_path.exists() else None
        return result.returncode, calls, deployed, commit

    def test_fetch_failure_does_not_reset_or_run_containers(self):
        status, calls, deployed, _ = self.run_deployment(fetch_status=17)
        self.assertEqual(status, 17)
        self.assertEqual(calls, ['git fetch origin develop'])
        self.assertIsNone(deployed)

    def test_reset_failure_does_not_run_containers(self):
        status, calls, deployed, _ = self.run_deployment(reset_status=18)
        self.assertEqual(status, 18)
        self.assertFalse(any(call.startswith('docker ') for call in calls))
        self.assertIsNone(deployed)

    def test_success_deploys_event_commit_instead_of_cached_branch(self):
        status, calls, deployed, expected = self.run_deployment()
        self.assertEqual(status, 0)
        self.assertEqual(deployed, expected)
        self.assertIn('docker compose -f docker-compose.prod.yml up -d --build', calls)


if __name__ == '__main__':
    unittest.main()

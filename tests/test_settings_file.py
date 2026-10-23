"""settings.txt (games/totk/runtime/settings_file.h): parser, presets, the file the settings window writes and the environment
the launcher sets from it: tests/test_settings_file.c."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(shutil.which('xcrun'), 'needs the Xcode command line tools')
class SettingsFileTests(unittest.TestCase):
    def test_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            for version in ('', 'TOTK_GAME_V143'):
                with self.subTest(version=version or 'v0'):
                    probe = Path(tmp) / ('probe-' + (version or 'v0'))
                    build = subprocess.run(['xcrun', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                                            *(['-D' + version + '=1'] if version else []),
                                            str(ROOT / 'tests/test_settings_file.c'), '-o', str(probe)],
                                           capture_output=True, text=True)
                    self.assertEqual(build.returncode, 0, build.stderr[-2000:])
                    run = subprocess.run([str(probe)], capture_output=True, text=True, timeout=30)
                    self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                    self.assertIn('PASS', run.stdout)


if __name__ == '__main__':
    unittest.main()

"""The panel's 历史 (games/totk/runtime/hint_history.inc) from the hint service's hint-history.json: tests/hint_history_probe.m."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin", "AppKit requires macOS")
class HintHistoryTests(unittest.TestCase):
    def test_history_after_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "probe"
            build = subprocess.run(["xcrun", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                                    str(ROOT / "tests/hint_history_probe.m"), "-framework", "Cocoa", "-o", str(executable)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(executable), tmp], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("pass: panel history", run.stdout)


if __name__ == "__main__":
    unittest.main()

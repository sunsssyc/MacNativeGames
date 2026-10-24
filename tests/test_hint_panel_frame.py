"""The panel's place and size (games/totk/runtime/hint_panel_frame.inc): tests/hint_panel_frame_probe.m."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == "darwin", "AppKit requires macOS")
class HintPanelFrameTests(unittest.TestCase):
    def test_drag_resize_and_keep(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "probe"
            build = subprocess.run(["xcrun", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function",
                                    str(ROOT / "tests/hint_panel_frame_probe.m"), "-framework", "Cocoa", "-o", str(executable)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(executable), tmp], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("pass: panel drag and resize", run.stdout)


if __name__ == "__main__":
    unittest.main()

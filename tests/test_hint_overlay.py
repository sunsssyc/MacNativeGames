"""Native hint actions use temporary configuration and never call a model."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

@unittest.skipUnless(sys.platform == "darwin", "AppKit requires macOS")
class HintOverlayTests(unittest.TestCase):
    def test_enable_cancel_and_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "probe"
            build = subprocess.run(["xcrun", "clang", "-fobjc-arc", "-Wall", "-Wextra", "-Werror",
                "-Wno-deprecated-declarations", str(ROOT / "tests/hint_overlay_probe.m"),
                "-framework", "Cocoa", "-framework", "AVFoundation", "-framework", "Speech", "-framework", "ScreenCaptureKit", "-o", str(executable)], capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(executable), tmp], capture_output=True, text=True, timeout=20)
            self.assertEqual(run.returncode, 0, run.stderr)

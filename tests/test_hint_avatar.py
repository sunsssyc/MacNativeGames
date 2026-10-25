"""Validate sprite assets, real assistant states and animation timer lifecycle."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
@unittest.skipUnless(sys.platform == 'darwin', 'AppKit requires macOS')
class HintAvatarTests(unittest.TestCase):
    def test_skeletal_avatar(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'avatar-probe'
            build=subprocess.run(['xcrun','clang','-fobjc-arc','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations',str(ROOT/'tests/hint_avatar_probe.m'),'-framework','Cocoa','-framework','AVFoundation','-framework','Speech','-framework','ScreenCaptureKit','-o',str(exe)],capture_output=True,text=True,timeout=60)
            self.assertEqual(build.returncode,0,build.stderr)
            run=subprocess.run([str(exe),tmp],cwd=ROOT/'games/totk',capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stderr)

"""No game data required: guard failures and time-dependent transitions."""
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
class CompanionActivityTests(unittest.TestCase):
    def test_decoder_and_transitions(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'probe'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(ROOT/'tests/companion_activity_probe.c'),'-o',str(exe)],check=True,capture_output=True)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
            self.assertEqual(result.returncode,0,result.stderr)

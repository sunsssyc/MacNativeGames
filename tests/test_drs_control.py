"""Automatic resolution control and the 1.4.3 host integration, without game data."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

TOTK = Path(__file__).resolve().parents[1] / 'games/totk'


class DrsTests(unittest.TestCase):
    def probe(self, source, runtime=False):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            self.skipTest('C compiler required')
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'probe'
            command = [compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                       f'-I{TOTK}/runtime', str(TOTK / 'tests/drs_control' / source), '-o', str(binary)]
            if runtime:
                command += ['-D_DARWIN_C_SOURCE', '-O1', '-Wl,-dead_strip']
            build = subprocess.run(command, capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(json.loads(run.stdout.strip().splitlines()[-1])['failures'], 0)

    def test_controller(self):
        self.probe('probe.c')

    @unittest.skipUnless(sys.platform == 'darwin', 'runtime requires macOS SDK')
    def test_runtime(self):
        self.probe('runtime_probe.c', runtime=True)


if __name__ == '__main__':
    unittest.main()

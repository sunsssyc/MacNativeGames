"""The settings behind the in-game settings menu (games/totk/runtime/settings_panel.m): tests/settings_panel_probe.m makes
the menu's calls against the production key 2 / 3 / 4 / 5 code, with and without the frame-rate cap and the resolution
controller, writing settings.txt to a temporary folder or to nothing."""
from pathlib import Path
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
# The weak references the settings make (games/totk/Makefile SETTINGS_OPTIONAL); missing ones are NULL.
OPTIONAL = ['nvn_set_fps_cap', 'nvn_fps_cap', 'nvn_fps_cap_pacing', 'runtime_drs_set', 'runtime_drs_enabled', 'runtime_drs_scale', 'runtime_drs_min',
            'runtime_drs_set_min', 'runtime_drs_set_target_ms']


@unittest.skipUnless(sys.platform == 'darwin', 'AppKit requires macOS')
class SettingsPanel(unittest.TestCase):
    def test_menu_model(self):
        compiler = shutil.which('clang')
        if not compiler:
            self.skipTest('clang is required')
        sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-version'], text=True)
        if int(sdk.split('.')[0]) < 26 or int(platform.mac_ver()[0].split('.')[0]) < 26:
            self.skipTest('The production Metal 4 mode implementations require macOS 26 and its SDK')
        gfx = ROOT / 'games/totk/third_party/d2r_gfx/gfx/nvn'
        with tempfile.TemporaryDirectory() as directory:
            for version in ('', 'TOTK_GAME_V143'):
                for optional in (False, True):
                    name = 'settings-panel-' + (version or 'base') + ('-optional' if optional else '')
                    executable = Path(directory) / name
                    command = [compiler, '-DSETTINGS_PANEL_PROBE=1', '-std=c11', '-fobjc-arc', '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations',
                               '-I' + str(gfx / 'include'), '-Wl,-undefined,dynamic_lookup', '-Wl,-dead_strip', '-Wl,-U,_probe_cap_paused',
                               *['-Wl,-U,_' + symbol for symbol in OPTIONAL],
                               str(ROOT / 'tests/settings_panel_probe.m'), str(ROOT / 'tests/shortcut_output_fixture.c'),
                               str(gfx / 'totk_mfx.m'), str(gfx / 'totk_mfx_up.m'), str(gfx / 'totk_taa.m'),
                               *([str(ROOT / 'tests/settings_panel_optional.c')] if optional else []),
                               '-framework', 'Cocoa', '-framework', 'Metal', '-framework', 'MetalFX',
                               '-framework', 'QuartzCore', '-framework', 'CoreVideo', '-o', str(executable)]
                    if version:
                        command.append('-D' + version + '=1')
                    build = subprocess.run(command, capture_output=True, text=True, timeout=120)
                    self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
                    for language, written in (('en', True), ('zh', False)):
                        with self.subTest(version=version or 'base', optional=optional, language=language, written=written):
                            settings = Path(directory) / (name + '-' + language) / 'settings.txt'
                            settings.parent.mkdir()
                            env = {k: v for k, v in os.environ.items()
                                   if not k.startswith('TOTK_') or k in ('TOTK_HUD',)}
                            env.update(TOTK_UI_LANG=language, TOTK_OUTPUT_RES='2560x1440', TOTK_MFX='0',
                                       TOTK_MFX_OUTPUT='0', TOTK_MFX_UPSCALE='0', TOTK_TAA='0')
                            run = subprocess.run([str(executable), str(settings) if written else '-'], env=env,
                                                 capture_output=True, text=True, timeout=60)
                            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
                            self.assertIn('pass: settings menu model', run.stdout)
                            self.assertEqual(settings.exists(), written)


if __name__ == '__main__':
    unittest.main()

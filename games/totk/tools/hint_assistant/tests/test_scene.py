"""指给我看 without a model: marks are checked and scaled, offered only with the player's picture, and returned."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from totk_hint import backends, config, harness, scene, service


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(config.DEFAULTS)

    def test_marks_are_checked_and_written_as_fractions(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder, 'marks.json')
            reply = scene.mark({'marks': [{'kind': 'circle', 'x': 640, 'y': 200, 'label': '木板'},
                                          {'kind': 'arrow', 'x': 100, 'y': 700, 'to_x': 640, 'to_y': 200, 'label': '接到这里'}]},
                               1280, 800, out)
            self.assertTrue(reply['ok'])
            self.assertEqual(scene.read_marks(out), [{'kind': 'circle', 'at': [0.5, 0.25], 'label': '木板'},
                                                    {'kind': 'arrow', 'at': [0.0781, 0.875], 'label': '接到这里', 'to': [0.5, 0.25]}])
            for bad in ({'marks': []}, {'marks': [{'kind': 'box', 'x': 1, 'y': 1, 'label': 'a'}]},
                        {'marks': [{'kind': 'circle', 'x': 1300, 'y': 1, 'label': 'a'}]},
                        {'marks': [{'kind': 'circle', 'x': 1, 'y': 1, 'label': ''}]},
                        {'marks': [{'kind': 'arrow', 'x': 1, 'y': 1, 'label': 'a'}]},
                        {'marks': [{'kind': 'circle', 'x': True, 'y': 1, 'label': 'a'}]},
                        {'marks': [{'kind': 'circle', 'x': 1, 'y': 1, 'label': 'a'}] * 5}):
                with self.assertRaises(ValueError, msg=bad):
                    scene.mark(bad, 1280, 800, out)

    def test_mark_screen_only_with_the_players_picture(self):
        self.assertNotIn('mark_screen', [s['name'] for s in harness.Harness().tool_specs()])
        with self.assertRaises(harness.ToolError):
            harness.Harness().call('mark_screen', {'marks': []})
        with tempfile.TemporaryDirectory() as folder:
            h = harness.Harness(marks=Path(folder, 'm.json'), scene_size=(1280, 800))
            self.assertIn('mark_screen', [s['name'] for s in h.tool_specs()])
            with self.assertRaises(harness.ToolError):   # a bad mark is the model's error to fix
                h.call('mark_screen', {'marks': [{'kind': 'circle', 'x': 9999, 'y': 1, 'label': 'a'}]})
            h.call('mark_screen', {'marks': [{'kind': 'circle', 'x': 10, 'y': 10, 'label': '这里'}]})
            self.assertTrue(Path(folder, 'm.json').is_file())
        ctx = backends.Context(self.config)
        self.assertIsNone(ctx.marks)
        ctx.scene_size = (1280, 800)
        args = ctx.mcp_command()[1]
        self.assertEqual(args[args.index('--marks') + 1], str(ctx.workdir / 'marks.json'))
        self.assertEqual(args[args.index('--scene-size') + 1], '1280x800')

    def test_a_pointing_question_attaches_the_paused_frame_and_returns_marks(self):
        with tempfile.TemporaryDirectory() as folder:
            server = service.Service(self.config, folder, log=lambda _: None)
            seen = {}
            def fake_hint(*args, scene_image=None, scene_size=None, **kwargs):
                seen.update(image=scene_image, size=scene_size)
                return {'text': '圈出的木板接到桥上。', 'backend': 'codex', 'seconds': 1, 'attempts': [],
                        'marks': [{'kind': 'circle', 'at': [0.5, 0.25], 'label': '木板'}]}
            prepared = (Path(folder, 'hint-scene.jpg'), 1280, 800)
            with patch.object(service, 'hint', side_effect=fake_hint), patch.object(service.scenemod, 'prepare', return_value=prepared):
                server.current = (1, threading.Event(), None)
                server.work({'id': 1, 'session': 1, 'tier': 1, 'question': '怎么过', 'scene': True}, server.current[1])
                self.assertEqual((seen['image'], tuple(seen['size'])), (prepared[0], (1280, 800)))
                answer = json.loads(Path(folder, service.RESPONSE).read_text())
                self.assertEqual(answer['marks'], [{'kind': 'circle', 'at': [0.5, 0.25], 'label': '木板'}])
                server.current = (2, threading.Event(), None)
                server.work({'id': 2, 'session': 1, 'tier': 1, 'question': '怎么过'}, server.current[1])
                self.assertEqual((seen['image'], seen['size']), (None, None))   # no 指给我看: no picture
        prompt = []
        backend = type('B', (), {'available': lambda self: (True, ''), 'title': 'B',
                                 'run': lambda self, system, p, ctx: prompt.append((p, ctx.marks)) or {'text': '好'}})()
        with patch.object(backends, 'make', return_value=backend):
            service.hint(self.config, 1, 'codex', '怎么过', None, False, scene_image=Path('/tmp/s.jpg'), scene_size=(1280, 800))
        self.assertIn('mark_screen', prompt[0][0])
        self.assertIn('1280×800', prompt[0][0])
        self.assertTrue(str(prompt[0][1]).endswith('marks.json'))


if __name__ == '__main__':
    unittest.main()

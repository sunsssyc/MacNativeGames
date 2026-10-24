import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from totk_hint import live

class LiveTests(unittest.TestCase):
    def test_reject_invalid_action_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            for button,ms in [('unknown',100),('a',1001),('a',True),('a',-1)]:
                with self.assertRaises(ValueError):live.call('press',button,ms,folder)
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_matches_request_id_not_stale_reply(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'runtime-response.json').write_text(json.dumps({'id':'old','ok':True}))
            def runtime():
                deadline=time.monotonic()+2
                while time.monotonic()<deadline:
                    try:q=json.loads((root/'runtime-request.json').read_text())
                    except (OSError,ValueError):time.sleep(.01);continue
                    (root/'runtime-response.json').write_text(json.dumps({'id':q['id'],'ok':True,'state':{'source':'live_runtime','player_present':False}}));return
            thread=threading.Thread(target=runtime);thread.start()
            result=live.call(folder=folder);thread.join()
            self.assertNotEqual(result['id'],'old')
            self.assertFalse(result['state']['player_present'])


class LiveViewTests(unittest.TestCase):
    def test_actors_are_named_placed_and_filtered(self):
        from totk_hint import harness
        state = {'player_present': True, 'position': [0, 16.6, 130], 'facing': [0, 0, -1],
                 'nearby': [{'name': 'Armor_Default_Upper', 'position': [0, 16.6, 130], 'distance': 0.1},
                            {'name': 'Weapon_Lsword_164', 'position': [0, 17.7, 130.2], 'distance': 1.2},
                            {'name': 'PlayerCamera', 'position': [0, 18.4, 135.2], 'distance': 5.4},
                            {'name': 'DgnObj_Small_Warpin_B_02', 'position': [0, 16.5, 132], 'distance': 1.9},
                            {'name': 'SpObj_LiftGeneratorWing_A_01', 'position': [16.5, 14.7, 76.5], 'distance': 56.1},
                            {'name': 'TrolleyRailManagementActor', 'position': [-0.5, 21, 74], 'distance': 56.2},
                            {'name': 'Weapon_Sword_002', 'position': [8, 16.6, 122], 'distance': 11.3},
                            {'name': 'SoulSage_NormalArrow', 'position': [1, 17, 128], 'distance': 2.3},
                            {'name': 'SpObj_Cart_A_01', 'position': [-20, -18, -24], 'distance': 159.3},
                            {'name': 'SpObj_Cart_A_01', 'position': [-56, 0, -24], 'distance': 164.8}]}
        view = harness.live_view(state)
        self.assertEqual(view['facing_text'], '面朝北')
        names = [a['name'] for a in view['nearby']]
        self.assertEqual(names, ['DgnObj_Small_Warpin_B_02', 'SpObj_LiftGeneratorWing_A_01', 'TrolleyRailManagementActor',
                                 'Weapon_Sword_002', 'SpObj_Cart_A_01'])   # worn gear, cameras, arrows go; a sword stays
        self.assertEqual(view['nearby'][-1]['count'], 2)   # two carts: one line
        wing = view['nearby'][1]
        self.assertEqual((wing['kind'], wing['gloss'], wing['side']), ('机关装置', '翅膀 生成装置', '正前方'))   # 17° right
        self.assertEqual(view['nearby'][0]['side'], '正后方')   # the warp is behind Link (+z while facing -z)
        self.assertEqual(view['nearby'][2]['gloss'], '矿车轨道')
        self.assertEqual(view['nearby'][3]['side'], '右前方')   # the sword: 8 m ahead and 8 m right
        self.assertIn('神庙', view['scene_guess'])
        title = harness.live_view({'position': [0, -0.15, 0], 'facing': [0, 0, 1], 'nearby': []})
        self.assertIn('标题', title['scene_guess'])
        self.assertEqual(harness.live_view({'player_present': False}), {'player_present': False})

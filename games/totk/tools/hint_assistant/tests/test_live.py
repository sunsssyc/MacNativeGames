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

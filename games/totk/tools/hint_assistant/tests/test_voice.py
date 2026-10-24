"""朗读 without a model or the network: lines, voice choice, streaming jobs, cancel, setup, Google's monthly cap."""
import base64
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
import wave
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from totk_hint import config, service, voice


def reply(folder):
    return json.loads(Path(folder, voice.RESPONSE).read_text())


def wait_for(condition, seconds=3):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if condition():
                return True
        except (OSError, ValueError):   # the reply file is being replaced
            pass
        time.sleep(0.01)
    return False


class FakeEngine:
    name = 'fake'

    def __init__(self, delay=0.0):
        self.spoken, self.delay = [], delay

    def prepare(self):
        pass

    def speak(self, text, out):
        time.sleep(self.delay)
        self.spoken.append(text)
        Path(out).write_bytes(b'RIFF')


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.config = copy.deepcopy(config.DEFAULTS)

    def service(self, engine=None):
        s = voice.VoiceService(self.folder.name, self.config, lambda _: None)
        patcher = patch.object(s, 'engine', return_value=engine)
        patcher.start()
        self.addCleanup(patcher.stop)
        return s

    def test_lines_are_bounded_and_unfinished_lines_wait(self):
        self.assertEqual(voice.request_lines({'lines': [' 往北走 ', '找英帕']}), ['往北走', '找英帕'])
        for bad in ({}, {'lines': []}, {'lines': 'x'}, {'lines': ['']}, {'lines': [1]},
                    {'lines': ['中' * (voice.MAX_LINE_CHARS + 1)]}, {'lines': ['a'] * (voice.MAX_LINES + 1)}):
            self.assertIsNone(voice.request_lines(bad), bad)
        self.assertEqual(voice.finished_lines('往北走\n再找', False), ['往北走'])
        self.assertEqual(voice.finished_lines('往北走\n再找英帕。', False), ['往北走', '再找英帕。'])   # a sentence ended
        self.assertEqual(voice.finished_lines('往北走\n再找', True), ['往北走', '再找'])

    def test_no_voice_here_lets_the_game_read_with_the_system_voice(self):
        s = self.service(None)
        s.start('a', ['往北走'])
        self.assertTrue(wait_for(lambda: reply(self.folder.name)['status'] == 'system'))

    def test_engine_choice(self):
        s = voice.VoiceService(self.folder.name, self.config, lambda _: None)
        with patch.object(voice.Voice, 'ready', return_value=True), patch.object(voice.GoogleVoice, 'ready', return_value=True):
            self.assertIs(s.engine(), s.voice)   # a recorded clone wins
            s.settings = {'engine': 'google'}
            self.assertIs(s.engine(), s.google)
            s.settings = {'engine': 'system'}
            self.assertIsNone(s.engine())
        with patch.object(voice.Voice, 'ready', return_value=False), patch.object(voice.GoogleVoice, 'ready', return_value=True):
            s.settings = {'engine': 'auto'}
            self.assertIs(s.engine(), s.google)
        with patch.object(voice.Voice, 'ready', return_value=True), patch.object(voice.VoiceService, 'installing', return_value=True), \
             patch.object(voice.GoogleVoice, 'ready', return_value=False):
            self.assertIsNone(s.engine())   # never the clone while it is being installed

    def test_streamed_lines_are_read_in_order_and_a_rewritten_line_again(self):
        engine = FakeEngine()
        s = self.service(engine)
        s.start('r1', final=False)
        s.feed('r1', '我先查一下')                       # unfinished: nothing yet
        time.sleep(0.1)
        self.assertEqual(engine.spoken, [])
        s.feed('r1', '')                                 # a tool call: those words were not the answer
        s.feed('r1', '往北走。\n再去找英帕')
        self.assertTrue(wait_for(lambda: engine.spoken == ['往北走。']))
        s.feed('r1', '往北走到驿站。\n再去找英帕。', final=True)   # the first line changed on the way
        self.assertTrue(wait_for(lambda: reply(self.folder.name)['status'] == 'done'))
        self.assertEqual(engine.spoken, ['往北走。', '往北走到驿站。', '再去找英帕。'])
        files = reply(self.folder.name)['files']
        self.assertEqual(len(files), 2)
        self.assertTrue(all(Path(f).is_file() for f in files))

    def test_cancel_and_a_newer_answer_stop_the_old_one(self):
        engine = FakeEngine(delay=0.2)
        s = self.service(engine)
        s.handle({'id': 'old', 'lines': ['一', '二', '三']})
        self.assertTrue(wait_for(lambda: engine.spoken))
        s.handle({'id': 'old', 'cancel': True})
        time.sleep(0.5)
        self.assertLess(len(engine.spoken), 3)
        self.assertFalse(Path(self.folder.name, voice.RESPONSE).exists() and reply(self.folder.name)['status'] == 'done')
        s.handle({'id': 'new', 'lines': ['新的']})
        self.assertTrue(wait_for(lambda: reply(self.folder.name)['id'] == 'new' and reply(self.folder.name)['status'] == 'done'))
        s.handle({'id': 5, 'lines': ['x']})   # ids are strings
        time.sleep(0.1)
        self.assertEqual(reply(self.folder.name)['id'], 'new')

    def test_a_failing_voice_hands_over_to_the_system_voice(self):
        engine = FakeEngine()
        def broken(text, out):
            raise voice.VoiceError('Google 朗读失败：HTTP 403')
        engine.speak = broken
        s = self.service(engine)
        s.start('x', ['往北走'])
        self.assertTrue(wait_for(lambda: reply(self.folder.name)['status'] == 'system'))
        self.assertEqual(reply(self.folder.name)['files'], [])

    def test_google_counts_characters_and_stops_at_the_monthly_cap(self):
        self.config['voice'] = dict(self.config['voice'], google_monthly_chars=10)
        g = voice.GoogleVoice(self.folder.name, self.config)
        audio = b'RIFF....WAVEfmt '
        def urlopen(request, timeout):
            body = json.loads(request.data)
            self.assertEqual(body['voice']['name'], voice.GOOGLE_VOICE)
            self.assertEqual(request.headers['X-goog-user-project'], 'p')
            return io.BytesIO(json.dumps({'audioContent': base64.b64encode(audio).decode()}).encode())
        with patch.object(voice.urllib.request, 'urlopen', side_effect=urlopen), \
             patch.object(voice.GoogleVoice, '_token', return_value='t'), \
             patch('totk_hint.vertex.project_and_region', return_value=('p', 'global')):
            out = Path(self.folder.name, 'a.wav')
            g.speak('往北走到驿站。', out)
            self.assertEqual(out.read_bytes(), audio)
            self.assertEqual(g.used(), 7)
            with self.assertRaises(voice.VoiceError):
                g.speak('再去找英帕。', out)   # 7 + 6 > 10
        with patch('totk_hint.vertex.gcloud', return_value='/bin/gcloud'), \
             patch('totk_hint.vertex.project_and_region', return_value=('p', 'global')):
            self.assertTrue(g.ready())
            g.usage.write_text(json.dumps({time.strftime('%Y-%m'): 10}))
            self.assertFalse(g.ready())

    def test_setup_answers_apart_and_is_not_interrupted_by_reading(self):
        s = self.service(FakeEngine())
        release = threading.Event()
        def install(progress=lambda text: None, cancel=None):
            progress('正在下载……'); release.wait(2)
        setup = Path(self.folder.name, voice.SETUP)
        with patch.object(voice.Voice, 'install', side_effect=install):
            s.handle({'id': 'setup', 'install': True})
            self.assertTrue(wait_for(lambda: json.loads(setup.read_text())['status'] == 'installing'))
            s.handle({'id': 'read', 'lines': ['往北走']})   # reading goes on while installing
            self.assertTrue(wait_for(lambda: reply(self.folder.name)['status'] == 'done'))
            s.handle({'id': 'again', 'install': True})     # one setup at a time
            self.assertEqual(json.loads(setup.read_text())['status'], 'error')
            release.set(); s.setup.join(2)
        self.assertEqual(json.loads(setup.read_text())['status'], 'installed')

    @unittest.skipUnless(sys.platform == 'darwin', 'afconvert is macOS')
    def test_reference_is_converted_and_kept_with_its_words(self):
        take = Path(self.folder.name, 'take.wav')
        with wave.open(str(take), 'wb') as f:
            f.setnchannels(2); f.setsampwidth(2); f.setframerate(48000); f.writeframes(b'\0\0' * 2 * 4800)
        v = voice.Voice(self.folder.name)
        self.assertIsNone(v.reference())
        with self.assertRaises(voice.VoiceError):
            v.set_reference(take, ' ')
        v.set_reference(take, '今天天气不错')
        wav, text = v.reference()
        with wave.open(str(wav)) as f:
            self.assertEqual((f.getnchannels(), f.getframerate()), (1, 24000))
        self.assertEqual(text, '今天天气不错')

    def test_a_reading_request_is_read_while_it_streams(self):
        engine = FakeEngine()
        server = service.Service(self.config, self.folder.name, log=lambda _: None)
        def fake_hint(*args, on_event=None, **kwargs):
            on_event('text', '往北走。')
            self.assertTrue(wait_for(lambda: engine.spoken == ['往北走。']))   # before the answer is done
            on_event('text', '往北走。\n再去找英帕')
            return {'text': '往北走。\n再去找英帕', 'backend': 'codex', 'seconds': 1, 'attempts': []}
        with patch.object(server.voice, 'engine', return_value=engine), patch.object(service, 'hint', side_effect=fake_hint):
            server.current = (7, threading.Event(), None)
            server.work({'id': 7, 'session': 7, 'tier': 1, 'question': '去哪', 'read': True}, server.current[1])
            self.assertTrue(wait_for(lambda: reply(self.folder.name)['status'] == 'done'))
        self.assertEqual(engine.spoken, ['往北走。', '再去找英帕'])
        self.assertEqual(reply(self.folder.name)['id'], '7')

    def test_service_loop_passes_voice_requests(self):
        server = service.Service(self.config, self.folder.name, log=lambda _: None)
        seen = []
        def alive(pid):   # the first check writes a request after start-up; the next one ends the loop
            if not Path(self.folder.name, voice.REQUEST).exists():
                service._write(Path(self.folder.name, voice.REQUEST), {'id': 'v1', 'lines': ['往北走']})
            return not seen
        with patch.object(server.voice, 'handle', side_effect=seen.append), \
             patch.object(service, '_alive', side_effect=alive), \
             patch.object(service.time, 'sleep'), patch.object(service.time, 'monotonic', side_effect=range(0, 300, 3)):
            self.assertEqual(server.run(parent_pid=1), 0)
        self.assertEqual(seen, [{'id': 'v1', 'lines': ['往北走']}])


if __name__ == '__main__':
    unittest.main()

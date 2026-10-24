"""朗读 without the model: the request/response contract, ordering, cancel and the reference voice."""
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import wave
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from totk_hint import service, voice


def reply(folder):
    return json.loads(Path(folder, voice.RESPONSE).read_text())


class VoiceTests(unittest.TestCase):
    def test_pages_are_bounded(self):
        self.assertEqual(voice.pages_of({'pages': [' 往北走 ', '找英帕']}), ['往北走', '找英帕'])
        for bad in ({}, {'pages': []}, {'pages': 'x'}, {'pages': ['']}, {'pages': [1]},
                    {'pages': ['中' * (voice.MAX_PAGE_CHARS + 1)]}, {'pages': ['a'] * (voice.MAX_PAGES + 1)}):
            self.assertIsNone(voice.pages_of(bad), bad)

    def test_not_installed_or_no_reference_lets_the_game_use_the_system_voice(self):
        with tempfile.TemporaryDirectory() as folder:
            s = voice.VoiceService(folder, {}, lambda _: None)
            s.current = ('a', threading.Event(), None)
            s.speak({'id': 'a', 'pages': ['往北走']}, s.current[1])
            self.assertEqual(reply(folder)['status'], 'missing')
            with patch.object(voice.Voice, 'installed', return_value=True):
                s.current = ('b', threading.Event(), None)
                s.speak({'id': 'b', 'pages': ['往北走']}, s.current[1])
            self.assertEqual(reply(folder)['status'], 'no_reference')

    def test_pages_are_spoken_in_order_and_a_cancel_stops(self):
        with tempfile.TemporaryDirectory() as folder:
            s = voice.VoiceService(folder, {}, lambda _: None)
            spoken = []
            def synthesize(text, out, reference=None, seed=None):
                spoken.append(text)
                Path(out).write_bytes(b'RIFF')
                return 0.1, 1.0
            with patch.object(voice.Voice, 'installed', return_value=True), \
                 patch.object(voice.Voice, 'reference', return_value=(Path('ref.wav'), '参考')), \
                 patch.object(voice.Voice, 'synthesize', side_effect=synthesize):
                s.current = ('c', threading.Event(), None)
                s.speak({'id': 'c', 'pages': ['第一页', '第二页']}, s.current[1])
                answer = reply(folder)
                self.assertEqual((answer['status'], spoken), ('done', ['第一页', '第二页']))
                self.assertTrue(all(Path(f).is_file() for f in answer['files']))
                cancel = threading.Event(); cancel.set(); spoken.clear()
                s.current = ('d', cancel, None)
                s.speak({'id': 'd', 'pages': ['不读']}, cancel)
                self.assertEqual(spoken, [])
                s.speak({'id': 'late', 'pages': ['旧请求']}, threading.Event())   # superseded: no reply written
                self.assertNotEqual(reply(folder)['id'], 'late')
                s.current = ('e', threading.Event(), None)
                def cancelled_midway(text, out, reference=None, seed=None):
                    s.current[1].set()
                    return synthesize(text, out)
                with patch.object(voice.Voice, 'synthesize', side_effect=cancelled_midway):
                    s.speak({'id': 'e', 'pages': ['读到一半取消']}, s.current[1])
                self.assertEqual((reply(folder)['id'], reply(folder)['files']), ('e', [None]))   # the page made after the cancel is dropped

    def test_handle_runs_one_job_and_cancel_stops_it(self):
        with tempfile.TemporaryDirectory() as folder:
            s = voice.VoiceService(folder, {}, lambda _: None)
            started = threading.Event()
            def slow(request, cancel):
                started.set(); cancel.wait(2)
            with patch.object(s, 'speak', side_effect=slow):
                s.handle({'id': 'one', 'pages': ['x']})
                started.wait(2)
                first = s.current
                s.handle({'id': 'one', 'cancel': True})
                first[2].join(2)
                self.assertTrue(first[1].is_set())
                self.assertIsNone(s.current)
            s.handle({'id': 5, 'pages': ['x']})   # ids are strings
            self.assertIsNone(s.current)

    def test_setup_answers_apart_and_is_not_interrupted_by_reading(self):
        with tempfile.TemporaryDirectory() as folder:
            s = voice.VoiceService(folder, {}, lambda _: None)
            release = threading.Event()
            def install(progress=lambda text: None, cancel=None):
                progress('正在下载……'); release.wait(2)
            with patch.object(voice.Voice, 'install', side_effect=install):
                s.handle({'id': 'setup', 'install': True})
                for _ in range(100):
                    if Path(folder, voice.SETUP).exists():
                        break
                    threading.Event().wait(0.01)
                self.assertEqual(json.loads(Path(folder, voice.SETUP).read_text())['status'], 'installing')
                s.handle({'id': 'read', 'pages': ['往北走']})   # reading while installing: the system voice reads
                s.current[2].join(2)
                self.assertEqual(reply(folder)['status'], 'missing')
                s.handle({'id': 'again', 'install': True})     # one setup at a time
                self.assertEqual(json.loads(Path(folder, voice.SETUP).read_text())['status'], 'error')
                release.set(); s.setup.join(2)
            self.assertEqual(json.loads(Path(folder, voice.SETUP).read_text())['status'], 'installed')

    @unittest.skipUnless(sys.platform == 'darwin', 'afconvert is macOS')
    def test_reference_is_converted_and_kept_with_its_words(self):
        with tempfile.TemporaryDirectory() as folder:
            take = Path(folder, 'take.wav')
            with wave.open(str(take), 'wb') as f:
                f.setnchannels(2); f.setsampwidth(2); f.setframerate(48000); f.writeframes(b'\0\0' * 2 * 4800)
            v = voice.Voice(folder)
            self.assertIsNone(v.reference())
            with self.assertRaises(voice.VoiceError):
                v.set_reference(take, ' ')
            v.set_reference(take, '今天天气不错')
            wav, text = v.reference()
            with wave.open(str(wav)) as f:
                self.assertEqual((f.getnchannels(), f.getframerate()), (1, 24000))
            self.assertEqual(text, '今天天气不错')

    def test_service_loop_passes_voice_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            server = service.Service({'tier_default': 1, 'total_timeout_seconds': 150}, folder, log=lambda _: None)
            seen = []
            def alive(pid):   # the first check writes a request after start-up; the next one ends the loop
                if not Path(folder, voice.REQUEST).exists():
                    service._write(Path(folder, voice.REQUEST), {'id': 'v1', 'pages': ['往北走']})
                return not seen
            with patch.object(server.voice, 'handle', side_effect=seen.append), \
                 patch.object(service, '_alive', side_effect=alive), \
                 patch.object(service.time, 'sleep'), patch.object(service.time, 'monotonic', side_effect=range(0, 300, 3)):
                self.assertEqual(server.run(parent_pid=1), 0)
            self.assertEqual(seen, [{'id': 'v1', 'pages': ['往北走']}])


if __name__ == '__main__':
    unittest.main()

"""Offline contract tests: no game, credentials, player saves or provider requests."""
import copy
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from totk_hint import backends, config, formats, harness, mcp_server, prompts, save, service


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(config.DEFAULTS)
        self.config['prefetch_state'] = False

    def test_backend_order_and_fallback(self):
        attempted = []
        def make(name, cfg):
            attempted.append(name)
            backend = Mock()
            backend.available.return_value = (True, '')
            if name == 'vertex':
                backend.run.return_value = {'text': '**先向北走。**'}
            else:
                backend.run.side_effect = backends.BackendError('offline fake failure')
            return backend
        with patch.object(backends, 'make', side_effect=make):
            result = service.hint(self.config, tier=2, allow_screenshot=False)
        self.assertEqual(attempted, list(config.BACKENDS))
        self.assertEqual(result['text'], '先向北走。')
        self.assertEqual(result['tier'], 2)
        self.assertEqual(len(result['attempts']), 3)

    def test_question_does_not_prefetch_even_with_legacy_config(self):
        cfg = copy.deepcopy(self.config)
        cfg['prefetch_state'] = True
        backend = Mock()
        backend.available.return_value = (True, '')
        backend.run.return_value = {'text': '你好'}
        with patch.object(service, 'compact_snapshot') as snapshot, patch.object(backends, 'make', return_value=backend):
            service.hint(cfg, question='你好', allow_screenshot=False,
                         runtime_snapshot={'secret_marker': 'unsolicited_runtime'})
        snapshot.assert_not_called()
        prompt = backend.run.call_args.args[1]
        self.assertNotIn('unsolicited_runtime', prompt)
        self.assertNotIn('请先调用 game_state', prompt)
        self.assertIn('按本次问题决定', prompt)

    def test_cancel_does_not_read_save_or_launch_backend(self):
        cancel = threading.Event(); cancel.set()
        with patch.object(service, 'compact_snapshot') as snapshot, patch.object(backends, 'make') as make:
            with self.assertRaises(backends.Cancelled):
                service.hint(config.DEFAULTS, cancel=cancel)
            snapshot.assert_not_called(); make.assert_not_called()
        ctx = backends.Context(self.config, cancel=cancel)
        with patch.object(backends.subprocess, 'Popen') as popen:
            with self.assertRaises(backends.Cancelled):
                backends.run_process(['unused'], ctx)
            popen.assert_not_called()

    def test_tiers_keep_previous_answers_and_drop_late_response(self):
        with tempfile.TemporaryDirectory() as folder:
            server = service.Service(self.config, folder, log=lambda _: None)
            fake = {'text': '向北走', 'backend': 'codex', 'seconds': 0, 'attempts': []}
            with patch.object(service, 'hint', return_value=fake) as hint:
                server.handle({'id': 'one', 'session': 'same', 'tier': 1})
                server.current[2].join(2)
                server.handle({'id': 'two', 'session': 'same', 'tier': 2})
                server.current[2].join(2)
                self.assertEqual(hint.call_args.args[4], [(1, '向北走')])
            response = Path(folder, service.RESPONSE)
            server.respond({'id': 'one', 'session': 'same'}, 'done', text='stale')
            answer = json.loads(response.read_text())
            self.assertEqual(answer['id'], 'two')
            self.assertEqual(answer['next_tier'], 3)

    def test_typed_followup_keeps_same_tier_questions_and_answers(self):
        with tempfile.TemporaryDirectory() as folder:
            server = service.Service(self.config, folder, log=lambda _: None)
            fake = {'text': '往北边的入口走', 'backend': 'codex', 'seconds': 0, 'attempts': []}
            with patch.object(service, 'hint', return_value=fake) as hint:
                server.work({'id': 1, 'session': 'same', 'tier': 1, 'question': '入口在哪里？'}, threading.Event())
                server.work({'id': 2, 'session': 'same', 'tier': 1, 'question': '那里离我多远？'}, threading.Event())
                previous = hint.call_args.args[4]
                self.assertEqual(previous, [{'tier': 1, 'question': '入口在哪里？', 'answer': '往北边的入口走'}])
                prompt = prompts.user_prompt(1, question='那里离我多远？', previous=previous)
                self.assertIn('入口在哪里？', prompt)
                self.assertIn('往北边的入口走', prompt)
                self.assertIn('那里离我多远？', prompt)
                self.assertIn('不自动升级', prompt)
                self.assertNotIn('这次要更进一步', prompt)
                server.work({'id': 3, 'session': 'new', 'tier': 1, 'question': '我在哪里？'}, threading.Event())
                self.assertEqual(hint.call_args.args[4], [])

    def test_conversation_history_is_bounded_and_keeps_recent_turns(self):
        with tempfile.TemporaryDirectory() as folder:
            server = service.Service(self.config, folder, log=lambda _: None)
            fake = {'text': '提示', 'backend': 'codex', 'seconds': 0, 'attempts': []}
            with patch.object(service, 'hint', return_value=fake) as hint:
                for i in range(service.MAX_HISTORY_TURNS + 2):
                    server.work({'id': i, 'session': 'same', 'tier': 1, 'question': f'问题{i}'}, threading.Event())
                self.assertEqual(len(server.sessions['same']), service.MAX_HISTORY_TURNS)
                self.assertEqual(server.sessions['same'][0]['question'], '问题2')
                self.assertEqual(len(hint.call_args.args[4]), service.MAX_HISTORY_TURNS)
                for i in range(service.MAX_SESSIONS):
                    server.work({'id': f'new{i}', 'session': f'new{i}', 'tier': 1}, threading.Event())
                self.assertEqual(len(server.sessions), service.MAX_SESSIONS)
                self.assertNotIn('same', server.sessions)

    def test_snapshot_is_not_current_environment(self):
        prompt = prompts.user_prompt(1, {'player': {'hearts_now': 3.5}}, '你好')
        self.assertIn('不是当前状态', prompt)
        self.assertIn('打招呼仅简短回应', prompts.SYSTEM)
        self.assertIn('标题菜单', prompts.SYSTEM)

    def test_cancelled_backend_answer_is_not_published(self):
        with tempfile.TemporaryDirectory() as folder:
            server = service.Service(self.config, folder, log=lambda _: None)
            cancel = threading.Event()
            def delayed(*args, **kwargs):
                cancel.set()
                return {'text': 'must not appear'}
            with patch.object(service, 'hint', side_effect=delayed):
                server.work({'id': 1, 'session': 1, 'tier': 1}, cancel)
            answer = json.loads(Path(folder, service.RESPONSE).read_text())
            self.assertEqual(answer['status'], 'cancelled')
            self.assertEqual(server.sessions, {})

    def test_service_accepts_startup_request(self):
        with tempfile.TemporaryDirectory() as folder:
            server = service.Service(self.config, folder, log=lambda _: None)
            request = {'id': 'startup', 'session': 'test', 'tier': 1}
            service._write(Path(folder, service.REQUEST), request)
            with patch.object(server, 'handle') as handle, patch.object(service, '_alive', side_effect=[True, False]), \
                 patch.object(service.time, 'sleep'), patch.object(service.time, 'monotonic', side_effect=[3, 6]):
                self.assertEqual(server.run(parent_pid=1, accept_pending=True), 0)
                handle.assert_called_once_with(request)

    def test_mcp_protocol_survives_bad_requests(self):
        h = harness.Harness(allow_screenshot=False)
        server = mcp_server.Server(h, log=lambda _: None)
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': ['bad']},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'screenshot'}},
            {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {'name': 'game_state', 'arguments': 1}},
            {'jsonrpc': '2.0', 'id': 6, 'method': 'ping'},
        ]
        incoming = io.BytesIO(b'invalid\n' + b'\n'.join(json.dumps(m).encode() for m in messages))
        outgoing = io.BytesIO(); server.run(incoming, outgoing)
        results = [json.loads(line) for line in outgoing.getvalue().splitlines()]
        self.assertEqual(len(results), 7)
        self.assertEqual(results[0]['error']['code'], -32700)
        self.assertEqual([t['name'] for t in results[2]['result']['tools']], ['wait_state', 'runtime_state', 'press_button', 'stop_action', 'game_state', 'quest_log', 'search_text'])
        self.assertEqual([r['error']['code'] for r in results[3:6]], [-32602] * 3)
        self.assertEqual(results[-1]['result'], {})
        self.assertEqual(harness.Harness(allow_screenshot=True).tool_specs()[-1]['name'], 'screenshot')

    def test_save_reader_synthetic_types_and_invalid_file(self):
        data = bytearray(0x50)
        struct.pack_into('<III', data, 0, save.MAGIC, 0x0049E946, 0x50)
        pairs = [(formats.murmur3('opened'), 1), (0, save.TYPES.index('Int')),
                 (formats.murmur3('rupees'), 123), (0, save.TYPES.index('Enum')),
                 (formats.murmur3('quest'), formats.murmur3('Complete'))]
        for i, pair in enumerate(pairs):
            struct.pack_into('<II', data, 0x28 + i * 8, *pair)
        parsed = save.SaveData(data)
        self.assertTrue(parsed.bool('opened'))
        self.assertEqual(parsed.int('rupees'), 123)
        self.assertEqual(parsed.enum('quest', {formats.murmur3('Complete'): 'Complete'}), 'Complete')
        self.assertIsNone(parsed.vec3('missing'))
        with self.assertRaises(ValueError): save.SaveData(b'bad')

    def test_chinese_quest_text_respects_current_step(self):
        h = harness.Harness()
        h._tables = Mock(quest_texts={'test': {'Start': '请前往监视堡垒。', 'Complete': '任务完成。'}})
        quest = {'name': 'test', 'steps': [{'name': 'Start', 'nolog': False}, {'name': 'Next', 'nolog': True}]}
        self.assertEqual(h._log_text(quest, 'Next'), '请前往监视堡垒。')
        self.assertIsNone(h._log_text(quest, 'NotReady'))

    def test_prompt_tiers_and_output_limits(self):
        for tier in (1, 2, 3):
            self.assertIn(prompts.TIER_NAMES[tier], prompts.user_prompt(tier))
        cleaned = prompts.clean('\n'.join(['# ' + '中' * 60] * 10))
        self.assertLessEqual(len(cleaned), prompts.MAX_CHARS)
        self.assertLessEqual(len(cleaned.splitlines()), prompts.MAX_LINES)

    def test_config_rejects_string_booleans(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder, 'assistant.json')
            path.write_text('{"enabled":"false"}')
            with self.assertRaises(ValueError): config.load(path)


if __name__ == '__main__':
    unittest.main()

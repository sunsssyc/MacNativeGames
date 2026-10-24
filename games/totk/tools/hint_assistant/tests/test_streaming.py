"""Progress while the model works: lines as they are written, the agents' event streams, the service's partial answer."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from totk_hint import backends, config, service


def fake_agent(folder, body):
    path = Path(folder, 'agent')
    path.write_text(f'#!{sys.executable}\nimport sys, json, time\n' + textwrap.dedent(body))
    path.chmod(0o755)
    return str(path)


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.config = copy.deepcopy(config.DEFAULTS)

    def test_lines_arrive_while_running_and_the_deadline_holds(self):
        with tempfile.TemporaryDirectory() as folder:
            agent = fake_agent(folder, '''
                print('one', flush=True); time.sleep(0.6); print('two', flush=True)
            ''')
            seen = []
            ctx = backends.Context(self.config, timeout=10)
            code, out, _ = backends.run_process([agent], ctx, on_line=lambda line: seen.append((line.strip(), time.monotonic())))
            self.assertEqual((code, [s for s, _ in seen]), (0, ['one', 'two']))
            self.assertGreater(seen[1][1] - seen[0][1], 0.4)   # the first line did not wait for the second
            chatty = fake_agent(folder, '''
                while True:
                    print('still here', flush=True); time.sleep(0.05)
            ''')
            t0 = time.monotonic()
            with self.assertRaises(backends.BackendError):
                backends.run_process([chatty], backends.Context(self.config, timeout=1), on_line=lambda line: None)
            self.assertLess(time.monotonic() - t0, 5)   # output that never stops does not hold off the timeout

    def test_claude_code_stream_reports_tools_and_only_the_final_words(self):
        events = [
            {'type': 'system', 'subtype': 'init'},
            {'type': 'stream_event', 'event': {'type': 'message_start'}},
            {'type': 'stream_event', 'event': {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '我先查一下'}}},
            {'type': 'stream_event', 'event': {'type': 'content_block_start',
                                               'content_block': {'type': 'tool_use', 'name': 'mcp__totk-harness__quest_log'}}},
            {'type': 'stream_event', 'event': {'type': 'message_start'}},
            {'type': 'stream_event', 'event': {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '往北'}}},
            {'type': 'stream_event', 'event': {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': '走。'}}},
            {'type': 'result', 'result': '往北走。', 'num_turns': 2, 'total_cost_usd': 0.01},
        ]
        with tempfile.TemporaryDirectory() as folder:
            agent = fake_agent(folder, f'''
                sys.stdin.read()
                for e in {json.dumps(events, ensure_ascii=False)!r} and json.loads({json.dumps(json.dumps(events, ensure_ascii=False))}):
                    print(json.dumps(e, ensure_ascii=False), flush=True)
            ''')
            seen = []
            cfg = dict(self.config, claude_code={'path': agent})
            ctx = backends.Context(cfg, on_event=lambda kind, value: seen.append((kind, value)))
            answer = backends.ClaudeCode(cfg).run('system', 'prompt', ctx)
        self.assertEqual(answer['text'], '往北走。')
        self.assertEqual(seen, [('text', '我先查一下'), ('tool', 'quest_log'), ('text', '往北'), ('text', '往北走。')])

    def test_codex_events_report_tools_and_the_message(self):
        with tempfile.TemporaryDirectory() as folder:
            agent = fake_agent(folder, '''
                if '--version' in sys.argv: print('codex-cli 1.0'); sys.exit(0)
                if 'features' in sys.argv: sys.exit(0)
                sys.stdin.read()
                out = sys.argv[sys.argv.index('-o') + 1]
                for e in ({'type': 'thread.started'},
                          {'type': 'item.started', 'item': {'type': 'mcp_tool_call', 'server': 'totk-harness', 'tool': 'game_state'}},
                          {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': '去驿站。'}}):
                    print(json.dumps(e, ensure_ascii=False), flush=True)
                open(out, 'w').write('去驿站。')
            ''')
            seen = []
            cfg = dict(self.config, codex={'path': agent})
            ctx = backends.Context(cfg, on_event=lambda kind, value: seen.append((kind, value)))
            answer = backends.Codex(cfg).run('system', 'prompt', ctx)
        self.assertEqual(answer['text'], '去驿站。')
        self.assertEqual(seen, [('tool', 'game_state'), ('text', '去驿站。')])

    def test_service_publishes_stage_and_partial_answer(self):
        with tempfile.TemporaryDirectory() as folder:
            server = service.Service(self.config, folder, log=lambda _: None)
            published = []
            real = service._write
            def write(path, value):
                if path.name == service.RESPONSE:
                    published.append({k: value.get(k) for k in ('status', 'stage', 'partial')})
                real(path, value)
            def fake_hint(*args, on_event=None, **kwargs):
                on_event('tool', 'quest_log')
                on_event('text', '**往北**')
                time.sleep(0.15)
                on_event('text', '**往北**走。')
                time.sleep(0.3)   # an agent ends a second or two after its last words
                return {'text': '往北走。', 'backend': 'codex', 'seconds': 1, 'attempts': []}
            with patch.object(service, '_write', side_effect=write), patch.object(service, 'hint', side_effect=fake_hint):
                server.current = (1, threading.Event(), None)
                server.work({'id': 1, 'session': 1, 'tier': 1, 'question': '去哪'}, server.current[1])
                time.sleep(0.25)   # no progress write lands after the answer
        self.assertIn({'status': 'working', 'stage': '正在看任务日志', 'partial': ''}, published)
        self.assertIn({'status': 'working', 'stage': '正在回答', 'partial': '往北'}, published)   # cleaned like the answer
        self.assertIn({'status': 'working', 'stage': '正在回答', 'partial': '往北走。'}, published)
        self.assertEqual(published[-1]['status'], 'done')


if __name__ == '__main__':
    unittest.main()

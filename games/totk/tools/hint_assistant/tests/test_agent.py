"""agent.py and memory.py offline: scripted providers, fake server-sent events, a fake harness, a temporary memory file."""
import base64
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from totk_hint import agent, backends, config, harness, memory, service, vertex


def text(t):
    return {'content': [{'type': 'text', 'text': t}], 'stop': 'end_turn', 'usage': {'input_tokens': 10, 'output_tokens': 5}}


def tool(name, args, block_id='t1', before=''):
    content = ([{'type': 'text', 'text': before}] if before else []) + [{'type': 'tool_use', 'id': block_id, 'name': name, 'input': args}]
    return {'content': content, 'stop': 'tool_use', 'usage': {'input_tokens': 10, 'output_tokens': 5}}


class Scripted:
    """A provider that gives the replies it was handed, streaming their text, and remembers every request."""
    name, model, vision = 'scripted', 'fake-1', True

    def __init__(self, *replies):
        self.replies, self.requests = list(replies), []

    def complete(self, system, messages, tools, timeout, on_text, check=None, tools_off=False):
        self.requests.append({'system': system, 'messages': copy.deepcopy(messages), 'tools': [t['name'] for t in tools or ()],
                              'tools_off': tools_off})
        reply = self.replies.pop(0)
        for block in reply['content']:
            if block.get('type') == 'text':
                for i in range(0, len(block['text']), 3):
                    on_text(block['text'][i:i + 3])
        return reply


class FakeHarness:
    config, romfs, roots = {}, None, []

    def __init__(self):
        self.calls = []

    def tool_specs(self):
        return [{'name': n, 'description': n, 'inputSchema': {'type': 'object', 'properties': {'target': {'type': 'string'}}}}
                for n in ('game_state', 'guide', 'memory', 'mark_screen')]

    def call(self, name, args=None):
        self.calls.append((name, args))
        if name == 'guide':
            return json.dumps({'sources': [{'source': 'IGN', 'text': 'Put the wing on the rail.'}]}), None
        if name == 'game_state':
            raise harness.ToolError('找不到存档')
        return '{}', None


def context(timeout=30):
    events = []
    ctx = backends.Context({}, timeout=timeout, on_event=lambda kind, value: events.append((kind, value)))
    return ctx, events


class AgentLoopTests(unittest.TestCase):
    def test_tools_then_streamed_answer(self):
        provider = Scripted(tool('guide', {'target': 'current'}, before='Let me check'),
                            tool('game_state', {}, 't2'), text('往左走，把翅膀放上轨道。'))
        ctx, events = context()
        h = FakeHarness()
        out = agent.Agent(provider, h, ctx).run('系统', [{'type': 'text', 'text': '怎么过'}])
        self.assertEqual(out['text'], '往左走，把翅膀放上轨道。')
        self.assertEqual((out['turns'], out['tool_calls']), (3, 2))
        self.assertEqual(out['usage'], {'input_tokens': 30, 'output_tokens': 15})
        self.assertEqual(h.calls, [('guide', {'target': 'current'}), ('game_state', {})])
        self.assertEqual(provider.requests[0]['tools'], ['game_state', 'guide', 'memory', 'mark_screen', 'plan', 'research'])
        second = provider.requests[1]['messages']
        self.assertEqual(second[-1]['content'][0]['tool_use_id'], 't1')
        self.assertIn('Put the wing', second[-1]['content'][0]['content'][0]['text'])
        error = provider.requests[2]['messages'][-1]['content'][0]
        self.assertTrue(error['is_error'])
        self.assertIn('找不到存档', error['content'][0]['text'])
        self.assertEqual([v for k, v in events if k == 'tool'], ['guide', 'game_state'])
        self.assertEqual([v for k, v in events if k == 'text'][-1], '往左走，把翅膀放上轨道。')

    def test_last_round_turns_tools_off(self):
        provider = Scripted(*[tool('guide', {}, f't{i}') for i in range(2)], text('先往北走。'))
        ctx, _ = context()
        out = agent.Agent(provider, FakeHarness(), ctx, max_turns=3).run('s', [{'type': 'text', 'text': 'q'}])
        self.assertEqual(out['text'], '先往北走。')
        self.assertEqual([r['tools_off'] for r in provider.requests], [False, False, True])

    def test_bad_arguments_and_unknown_tools_are_errors_the_model_sees(self):
        provider = Scripted(tool('guide', {'_invalid_json': '{x'}), tool('rm_rf', {}, 't2'), text('好的。'))
        ctx, _ = context()
        h = FakeHarness()
        agent.Agent(provider, h, ctx).run('s', [{'type': 'text', 'text': 'q'}])
        self.assertEqual(h.calls, [])
        first = provider.requests[1]['messages'][-1]['content'][0]
        self.assertIn('JSON', first['content'][0]['text'])
        second = provider.requests[2]['messages'][-1]['content'][0]
        self.assertIn('没有工具 rm_rf', second['content'][0]['text'])

    def test_plan_tool_keeps_and_ticks_steps(self):
        provider = Scripted(tool('plan', {'steps': ['查神庙', '查攻略']}), tool('plan', {'done': [1]}, 't2'), text('好。'))
        ctx, events = context()
        a = agent.Agent(provider, FakeHarness(), ctx)
        a.run('s', [{'type': 'text', 'text': 'q'}])
        self.assertEqual(a.plan, [['查神庙', True], ['查攻略', False]])
        result = json.loads(provider.requests[2]['messages'][-1]['content'][0]['content'][0]['text'])
        self.assertEqual(result['plan'], ['1. [x] 查神庙', '2. [ ] 查攻略'])
        self.assertIn(('tool', 'plan'), events)

    def test_research_helper_has_its_own_context_and_only_lookups(self):
        provider = Scripted(tool('research', {'question': '宝箱怎么拿'}),
                            tool('memory', {'action': 'note', 'text': 'x'}, 'r1'),   # not a lookup: refused
                            tool('guide', {'target': 'current'}, 'r2'),
                            text('用翅膀搭桥，站上去用通天术（IGN）。'),
                            text('宝箱：用翅膀搭桥再用通天术。'))
        ctx, events = context()
        h = FakeHarness()
        out = agent.Agent(provider, h, ctx).run('主', [{'type': 'text', 'text': '宝箱在哪'}])
        self.assertEqual(out['text'], '宝箱：用翅膀搭桥再用通天术。')
        self.assertEqual(h.calls, [('guide', {'target': 'current'})])
        helper_first = provider.requests[1]
        self.assertEqual(helper_first['system'], agent.RESEARCH_SYSTEM)
        self.assertEqual(helper_first['tools'], ['game_state', 'guide'])
        self.assertEqual(helper_first['messages'], [{'role': 'user', 'content': [{'type': 'text', 'text': '宝箱怎么拿'}]}])
        refused = provider.requests[2]['messages'][-1]['content'][0]
        self.assertTrue(refused['is_error'])
        findings = json.loads(provider.requests[4]['messages'][-1]['content'][0]['content'][0]['text'])
        self.assertIn('通天术', findings['findings'])
        texts = [v for k, v in events if k == 'text']
        self.assertFalse(any('IGN' in t for t in texts))   # the helper's notes never reach the panel
        self.assertEqual([v for k, v in events if k == 'tool'], ['research', 'memory', 'guide'])
        self.assertEqual(out['tool_calls'], 3)

    def test_text_protocol_for_models_without_tool_calling(self):
        provider = Scripted(text('<think>想一想</think>我查一下。<tool>{"name": "guide", "arguments": {"target": "current"}}</tool>'),
                            text('<think>好</think>往左走。'))
        ctx, events = context()
        h = FakeHarness()
        out = agent.Agent(provider, h, ctx, protocol='text').run('系统', [{'type': 'text', 'text': '怎么过'}])
        self.assertEqual(out['text'], '往左走。')
        self.assertEqual(h.calls, [('guide', {'target': 'current'})])
        first = provider.requests[0]
        self.assertEqual(first['tools'], [])
        self.assertIn('<tool>{"name": "工具名"', first['system'])
        self.assertIn('- guide：guide 参数：target（string）', first['system'])
        result = provider.requests[1]['messages'][-1]['content'][0]['text']
        self.assertTrue(result.startswith('<result name="guide">'))
        self.assertIn('Put the wing', result)
        self.assertFalse(any('<tool' in v or '想一想' in v for k, v in events if k == 'text'))

    def test_text_protocol_last_round_asks_for_the_answer(self):
        call = text('<tool>{"name": "guide", "arguments": {}}</tool>')
        provider = Scripted(call, text('去北边。'))
        ctx, _ = context()
        out = agent.Agent(provider, FakeHarness(), ctx, protocol='text', max_turns=2).run('s', [{'type': 'text', 'text': 'q'}])
        self.assertEqual(out['text'], '去北边。')
        self.assertIn('最后一轮', provider.requests[1]['messages'][-1]['content'][-1]['text'])

    def test_no_answer_is_an_error(self):
        provider = Scripted({'content': [], 'stop': 'refusal', 'usage': {}})
        ctx, _ = context()
        with self.assertRaisesRegex(backends.BackendError, 'declined'):
            agent.Agent(provider, FakeHarness(), ctx).run('s', [{'type': 'text', 'text': 'q'}])


ANTHROPIC_EVENTS = [
    {'type': 'message_start', 'message': {'model': 'claude-x', 'usage': {'input_tokens': 12}}},
    {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': ''}},
    {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': '先查'}},
    {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'signature_delta', 'signature': 'sig'}},
    {'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'text', 'text': ''}},
    {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': '我'}},
    {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': '查'}},
    {'type': 'content_block_start', 'index': 2, 'content_block': {'type': 'tool_use', 'id': 'tu', 'name': 'guide', 'input': {}}},
    {'type': 'content_block_delta', 'index': 2, 'delta': {'type': 'input_json_delta', 'partial_json': '{"target": '}},
    {'type': 'content_block_delta', 'index': 2, 'delta': {'type': 'input_json_delta', 'partial_json': '"current"}'}},
    {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use'}, 'usage': {'output_tokens': 7}},
    {'type': 'message_stop'}]


class ProviderTests(unittest.TestCase):
    def test_anthropic_stream_is_put_together(self):
        seen = []
        reply = agent.anthropic_reply(iter(ANTHROPIC_EVENTS), seen.append)
        self.assertEqual(seen, ['我', '查'])
        self.assertEqual(reply['stop'], 'tool_use')
        self.assertEqual(reply['usage'], {'input_tokens': 12, 'output_tokens': 7})
        self.assertEqual(reply['content'], [{'type': 'thinking', 'thinking': '先查', 'signature': 'sig'},
                                            {'type': 'text', 'text': '我查'},
                                            {'type': 'tool_use', 'id': 'tu', 'name': 'guide', 'input': {'target': 'current'}}])
        with self.assertRaisesRegex(backends.BackendError, 'overloaded'):
            agent.anthropic_reply(iter([{'type': 'error', 'error': {'message': 'overloaded'}}]), seen.append)

    def test_anthropic_request(self):
        p = agent.AnthropicProvider({'model': 'm', 'api_key_env': 'TEST_KEY_ENV', 'effort': 'low'})
        with patch.dict('os.environ', {'TEST_KEY_ENV': 'k'}), \
             patch.object(agent, 'sse', return_value=iter(ANTHROPIC_EVENTS)) as sse:
            self.assertEqual(p.available(), (True, ''))
            p.complete('sys', [{'role': 'user', 'content': 'q'}], [{'name': 'a', 'description': 'd', 'inputSchema': {}}],
                       10, lambda t: None, tools_off=True)
        url, body, headers, timeout, check = sse.call_args.args
        self.assertEqual(url, 'https://api.anthropic.com/v1/messages')
        self.assertEqual(headers, {'anthropic-version': agent.ANTHROPIC_VERSION, 'x-api-key': 'k'})
        self.assertEqual((body['model'], body['stream'], body['tool_choice'], body['output_config']),
                         ('m', True, {'type': 'none'}, {'effort': 'low'}))
        self.assertEqual(body['tools'], [{'name': 'a', 'description': 'd', 'input_schema': {}}])
        with patch.dict('os.environ', {}, clear=True):
            self.assertFalse(agent.AnthropicProvider({'model': 'm', 'api_key_env': 'TEST_KEY_ENV'}).available()[0])

    def test_openai_messages_and_stream(self):
        p = agent.OpenAIProvider({'model': 'qwen3', 'base_url': 'http://localhost:11434/v1'})
        self.assertEqual(p.available(), (True, ''))   # a local server needs no key
        self.assertFalse(agent.OpenAIProvider({'model': 'gpt', 'api_key_env': 'NOPE_X'}).available()[0])
        messages = [{'role': 'user', 'content': [{'type': 'image', 'source': {'media_type': 'image/png', 'data': 'AAA'}},
                                                 {'type': 'text', 'text': '怎么过'}]},
                    {'role': 'assistant', 'content': [{'type': 'text', 'text': '查'},
                                                      {'type': 'tool_use', 'id': 'c1', 'name': 'guide', 'input': {'target': '当前'}}]},
                    {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'c1',
                                                  'content': [{'type': 'text', 'text': 'r'},
                                                              {'type': 'image', 'source': {'media_type': 'image/jpeg', 'data': 'BBB'}}]}]}]
        out = p.messages('sys', messages)
        self.assertEqual(out[0], {'role': 'system', 'content': 'sys'})
        self.assertEqual(out[1]['content'][1], {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,AAA'}})
        self.assertEqual(out[2]['tool_calls'][0]['function'], {'name': 'guide', 'arguments': '{"target": "当前"}'})
        self.assertEqual(out[3], {'role': 'tool', 'tool_call_id': 'c1', 'content': 'r'})
        self.assertEqual(out[4]['content'][0]['image_url']['url'], 'data:image/jpeg;base64,BBB')   # after the tool message
        chunks = [{'model': 'qwen3', 'choices': [{'delta': {'content': '我看'}}]},
                  {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'x', 'function': {'name': 'guide', 'arguments': '{"tar'}}]}}]},
                  {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': 'get": "current"}'}}]}}]},
                  {'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}], 'usage': {'prompt_tokens': 3}}]
        seen = []
        with patch.object(agent, 'sse', return_value=iter(chunks)) as sse:
            reply = p.complete('sys', messages, [{'name': 'guide', 'description': 'd', 'inputSchema': {'type': 'object'}}],
                               10, seen.append)
        url, body, headers = sse.call_args.args[:3]
        self.assertEqual(url, 'http://localhost:11434/v1/chat/completions')
        self.assertEqual(headers, {})
        self.assertEqual(body['tools'][0]['function']['parameters'], {'type': 'object'})
        self.assertEqual(seen, ['我看'])
        self.assertEqual(reply['stop'], 'tool_use')
        self.assertEqual(reply['content'], [{'type': 'text', 'text': '我看'},
                                            {'type': 'tool_use', 'id': 'x', 'name': 'guide', 'input': {'target': 'current'}}])

    def test_sse_reads_data_lines(self):
        class Response:
            def __iter__(self):
                return iter([b'event: ping\n', b'data: {"a": 1}\n', b'\n', b': comment\n', b'data: [DONE]\n', b'data: {"b": 2}\n'])

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False
        with patch('urllib.request.urlopen', return_value=Response()):
            self.assertEqual(list(agent.sse('http://x', {}, {}, 5)), [{'a': 1}])

    def test_gemini_on_vertex_keeps_the_thought_signature(self):
        rest = type('Rest', (), {'config': {'vertex': {'project': 'p'}}, 'available': lambda self: (True, ''),
                                 'token': lambda self: 'ya29.t'})()
        p = agent.GeminiProvider(rest, {'model': 'gemini-4-argon'})
        self.assertEqual(p.model, 'google/gemini-4-argon')
        self.assertEqual(p.url, 'https://aiplatform.googleapis.com/v1/projects/p/locations/global/endpoints/openapi/chat/completions')
        signature = {'google': {'thought_signature': 'AY89'}}
        chunks = [{'choices': [{'delta': {'role': 'assistant', 'tool_calls': [
                      {'extra_content': signature, 'function': {'arguments': '{"target":"current"}', 'name': 'guide'},
                       'id': 'call_1', 'index': 0, 'type': 'function'}]}}]},
                  {'choices': [{'delta': {'content': ''}, 'finish_reason': 'tool_calls'}],
                   'usage': {'prompt_tokens': 89, 'completion_tokens': 27}}]
        with patch.object(agent, 'sse', return_value=iter(chunks)) as sse:
            reply = p.complete('s', [{'role': 'user', 'content': 'q'}], [], 10, lambda t: None)
        self.assertEqual(sse.call_args.args[2], {'Authorization': 'Bearer ya29.t'})
        self.assertEqual(reply['usage'], {'input_tokens': 89, 'output_tokens': 27})
        self.assertEqual(reply['content'][0]['extra_content'], signature)
        back = p.messages('s', [{'role': 'assistant', 'content': reply['content']}])
        self.assertEqual(back[1]['tool_calls'][0]['extra_content'], signature)
        cfg = copy.deepcopy(config.DEFAULTS)
        cfg['agent'].update(provider='gemini', model=None)
        self.assertIsInstance(agent.AgentBackend(cfg).provider(), agent.GeminiProvider)

    def test_agent_backend_needs_a_model(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        self.assertFalse(agent.AgentBackend(cfg).available()[0])
        cfg['agent'].update(provider='openai', model='qwen3', base_url='http://127.0.0.1:1234/v1')
        self.assertEqual(agent.AgentBackend(cfg).available(), (True, ''))
        self.assertIsInstance(backends.make('agent', cfg), agent.AgentBackend)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.m = memory.Memory(Path(self.folder.name) / 'assistant-memory.json')

    def test_notes_answers_and_context(self):
        shrine = {'id': 'Dungeon045', 'name': '吉鲁塔古马奇神庙'}
        self.m.record_answer('这个神庙怎么过', 1, '先往左边走。\n第二行', shrine, 'claude-code')
        for i in range(4):
            self.m.record_answer(f'问题{i}', 2, f'回答{i}')
        note = self.m.note('玩家只想要方向，不要完整解法')
        self.m.note('玩家只想要方向，不要完整解法')   # the same sentence once
        lines = self.m.context(shrine)
        self.assertTrue(lines[0].startswith('- 记下的：玩家只想要方向，不要完整解法（'))
        self.assertEqual(sum('记下的' in l for l in lines), 1)
        self.assertTrue(any('在吉鲁塔古马奇神庙问“这个神庙怎么过”（1 档）→ 答“先往左边走。”' in l for l in lines))
        self.assertTrue(any('问题3' in l for l in lines))
        self.assertFalse(any('问题0' in l for l in lines))   # only the latest three besides the same place
        self.assertEqual(len(self.m.recall('神庙')['answers']), 1)
        self.assertEqual(len(self.m.recall(about='Dungeon045')['answers']), 1)
        self.assertTrue(self.m.forget(self.m.load()['notes'][0]['id']))
        self.assertEqual(self.m.load()['notes'], [])
        self.assertIsInstance(note, str)

    def test_bounded_and_survives_a_broken_file(self):
        self.m.path.write_text('not json')
        self.assertEqual(self.m.load()['answers'], [])
        for i in range(memory.MAX_ANSWERS + 5):
            self.m.record_answer('q', 1, 'a' * 200)
        data = self.m.load()
        self.assertEqual(len(data['answers']), memory.MAX_ANSWERS)
        self.assertLessEqual(len(data['answers'][0]['answer']), memory.ANSWER_CHARS)
        with self.assertRaises(ValueError):
            self.m.note('  ')

    def test_memory_tool_in_the_harness(self):
        h = harness.Harness({}, memory=self.m.path)
        self.assertIn('memory', [s['name'] for s in h.tool_specs()])
        saved = json.loads(h.call('memory', {'action': 'note', 'text': '玩家已经拿到究极手', 'about': 'Dungeon045'})[0])
        self.assertTrue(saved['saved'])
        found = json.loads(h.call('memory', {'action': 'recall', 'text': '究极手'})[0])
        self.assertEqual(found['notes'][0]['about'], 'Dungeon045')
        with self.assertRaises(harness.ToolError):
            h.call('memory', {'action': 'drop'})
        off = harness.Harness({'memory': {'enabled': False}}, memory=self.m.path)
        self.assertNotIn('memory', [s['name'] for s in off.tool_specs()])

    def test_hint_carries_memory_and_remembers_where(self):
        self.m.note('玩家不想被剧透')
        backend = type('B', (), {'available': lambda self: (True, ''),
                                 'run': lambda self, system, prompt, ctx: (seen.update(prompt=prompt, path=ctx.memory_path)
                                                                           or {'text': '往左。'})})()
        seen = {}
        cfg = copy.deepcopy(config.DEFAULTS)
        with patch.object(backends, 'make', return_value=backend), \
             patch.object(harness.Harness, 'whereabouts', return_value={'id': 'Dungeon045', 'name': '吉鲁塔古马奇神庙'}):
            result = service.hint(cfg, question='怎么过', allow_screenshot=False, memory=self.m)
        self.assertIn('记忆（之前在这台 Mac 上的求助', seen['prompt'])
        self.assertIn('玩家不想被剧透', seen['prompt'])
        self.assertEqual(seen['path'], self.m.path)
        self.assertEqual(result['about']['id'], 'Dungeon045')

    def test_config_checks_the_agent_settings(self):
        path = Path(self.folder.name) / 'assistant.json'
        path.write_text(json.dumps({'agent': {'provider': 'ollama'}}))
        with self.assertRaisesRegex(ValueError, 'agent.provider'):
            config.load(path)
        path.write_text(json.dumps({'agent': {'provider': 'openai', 'tool_protocol': 'react'}}))
        with self.assertRaisesRegex(ValueError, 'tool_protocol'):
            config.load(path)


class VertexCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        vertex._cache.clear()
        self.addCleanup(vertex._cache.clear)
        self.dir = Path(self.folder.name)
        key = self.dir / 'k.pem'
        subprocess.run([vertex.OPENSSL, 'genrsa', '-out', str(key), '2048'], check=True, capture_output=True)
        subprocess.run([vertex.OPENSSL, 'rsa', '-in', str(key), '-pubout', '-out', str(self.dir / 'pub.pem')], check=True,
                       capture_output=True)
        self.account = {'type': 'service_account', 'project_id': 'proj-from-key', 'private_key_id': 'kid1',
                        'private_key': key.read_text(), 'client_email': 'bot@proj.iam.gserviceaccount.com',
                        'token_uri': 'https://oauth2.example/token'}
        self.path = self.dir / 'sa.json'
        self.path.write_text(json.dumps(self.account))

    def test_service_account_signs_a_jwt_that_verifies(self):
        sent = {}

        def post(url, fields, timeout=30):
            sent.update(url=url, fields=fields)
            return {'access_token': 'ya29.test', 'expires_in': 3599}
        cfg = {'vertex': {'credentials': str(self.path)}}
        rest = vertex.VertexREST(cfg)
        with patch.object(vertex, '_post_form', side_effect=post), patch.object(vertex, 'gcloud', return_value=None):
            self.assertEqual(rest.available(), (True, ''))
            self.assertEqual(vertex.project_and_region(cfg), ('proj-from-key', 'global'))
            self.assertEqual(rest.token(), 'ya29.test')
            self.assertEqual(rest.token(), 'ya29.test')   # cached
        self.assertEqual(sent['url'], 'https://oauth2.example/token')
        self.assertEqual(sent['fields']['grant_type'], 'urn:ietf:params:oauth:grant-type:jwt-bearer')
        head, claims, signature = sent['fields']['assertion'].split('.')
        pad = lambda part: base64.urlsafe_b64decode(part + '=' * (-len(part) % 4))
        self.assertEqual(json.loads(pad(head)), {'alg': 'RS256', 'typ': 'JWT', 'kid': 'kid1'})
        body = json.loads(pad(claims))
        self.assertEqual((body['iss'], body['aud'], body['scope'], body['exp'] - body['iat']),
                         ('bot@proj.iam.gserviceaccount.com', 'https://oauth2.example/token', vertex.SCOPE, 3600))
        (self.dir / 'sig').write_bytes(pad(signature))
        check = subprocess.run([vertex.OPENSSL, 'dgst', '-sha256', '-verify', str(self.dir / 'pub.pem'), '-signature',
                                str(self.dir / 'sig')], input=f'{head}.{claims}'.encode(), capture_output=True)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ['k.pem', 'pub.pem', 'sa.json', 'sig'])

    def test_authorized_user_and_bad_files(self):
        user = self.dir / 'adc.json'
        user.write_text(json.dumps({'type': 'authorized_user', 'client_id': 'c', 'client_secret': 's', 'refresh_token': 'r',
                                    'quota_project_id': 'qp'}))
        cfg = {'vertex': {'credentials': str(user)}}
        with patch.object(vertex, '_post_form', return_value={'access_token': 'ya29.u'}) as post:
            self.assertEqual(vertex.VertexREST(cfg).token(), 'ya29.u')
        self.assertEqual(post.call_args.args[1]['grant_type'], 'refresh_token')
        self.assertEqual(vertex.project_and_region(cfg)[0], 'qp')
        bad = self.dir / 'bad.json'
        bad.write_text(json.dumps({'type': 'external_account'}))
        ok, why = vertex.VertexREST({'vertex': {'credentials': str(bad)}}).available()
        self.assertFalse(ok)
        self.assertIn('not a service account key', why)
        ok, why = vertex.VertexREST({'vertex': {'credentials': str(self.dir / 'missing.json')}}).available()
        self.assertFalse(ok)
        self.assertNotIn('private', why)

    def test_claude_code_on_vertex_gets_the_same_file(self):
        cfg = {'vertex': {'credentials': str(self.path), 'project': 'p'}, 'claude_code': {}}
        seen = {}

        def run(command, ctx, prompt, env, cwd, on_line):
            seen['env'] = env
            on_line(json.dumps({'type': 'result', 'result': '好。'}))
            return 0, '', ''
        backend = backends.ClaudeCode(cfg, vertex=True)
        with patch.object(backends, 'run_process', side_effect=run), patch.object(backend, 'binary', return_value='/bin/claude'):
            self.assertEqual(backend.available(), (True, ''))
            ctx = backends.Context({})
            ctx.workdir = self.dir / 'run'
            backend.run('s', 'p', ctx)
        self.assertEqual(seen['env']['GOOGLE_APPLICATION_CREDENTIALS'], str(self.path))


class ChannelTests(unittest.TestCase):
    """assistant.json "channel" (the game's settings menu, 辅助 › AI 渠道) and what the menu reads back."""

    def test_channel_goes_first_and_keeps_the_rest(self):
        cfg = copy.deepcopy(config.DEFAULTS)
        self.assertEqual(backends.order('auto', cfg), list(config.BACKENDS))
        cfg['channel'] = 'agent'
        self.assertEqual(backends.order('auto', cfg), ['agent', 'claude-code', 'codex', 'vertex-claude-code', 'vertex'])
        self.assertEqual(backends.order('codex', cfg), ['codex'])   # a request naming a backend still gets only that one
        cfg['agent'].update(provider='gemini', model='gemini-4-argon')
        self.assertEqual(backends.label('agent', cfg), 'Gemini 4')
        cfg['agent'].update(provider='openai', model='qwen3.8:27b-mlx')
        self.assertEqual(backends.label('agent', cfg), 'qwen3.8:27b-mlx')
        self.assertEqual(backends.label('vertex', cfg), 'Claude（Vertex）')

    def test_service_reloads_settings_and_reports_channels(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'assistant.json'
            path.write_text(json.dumps({'enabled': True}))
            svc = service.Service(config.load(path), folder, log=lambda line: None)
            self.assertFalse(svc.reload())
            path.write_text(json.dumps({'enabled': True, 'channel': 'codex'}))
            os.utime(path, ns=(svc.config_stamp + 10**9, svc.config_stamp + 10**9))
            self.assertTrue(svc.reload())
            self.assertEqual(svc.config['channel'], 'codex')
            path.write_text('{ broken')
            os.utime(path, ns=(svc.config_stamp + 2 * 10**9, svc.config_stamp + 2 * 10**9))
            self.assertFalse(svc.reload())
            self.assertEqual(svc.config['channel'], 'codex')   # a file being edited keeps the last good settings
            with patch.object(backends, 'report', return_value=[('claude-code', True, ''), ('codex', False, 'no codex')]):
                svc.write_backends()
            written = json.loads((Path(folder) / service.BACKENDS).read_text())
            self.assertEqual(written['channel'], 'codex')
            self.assertEqual(written['order'][0], 'codex')
            self.assertEqual(written['backends']['codex'], {'ok': False, 'why': 'no codex', 'label': 'Codex'})

    def test_config_checks_the_channel(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'assistant.json'
            path.write_text(json.dumps({'channel': 'gemini'}))
            with self.assertRaisesRegex(ValueError, 'channel'):
                config.load(path)


if __name__ == '__main__':
    unittest.main()

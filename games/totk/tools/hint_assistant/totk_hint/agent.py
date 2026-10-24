"""The assistant's own agent loop, for a plain model behind an API: no Claude Code or Codex needed around it. After pi
(pi.dev): a small core that a model, a tool loop and a few tools make into an agent.

    providers  anthropic   Anthropic Messages API (api.anthropic.com, or any server speaking it); key from the env
               vertex      Anthropic models on Vertex AI (the vertex backend, vertex.py), gcloud sign-in
               openai      any OpenAI-compatible chat completions server: OpenAI, DeepSeek, Qwen, OpenRouter, or a
                           local one (Ollama, LM Studio, llama.cpp, mlx_lm.server) on localhost without a key
    loop       the model answers, or asks for tools; their results go back; up to max_turns rounds, the last one
               without tools so there is always an answer. Answers stream: on_event('text', so far).
    tools      the harness tools (game_state, quest_log, search_text, guide, memory, ...) plus
               plan      the model writes down what it will look up, and ticks it off (shown as 正在规划)
               research  a sub-agent with the read-only tools and its own context: it reads the long walkthroughs
                         and the game text and returns the facts with their sources, so the main context stays short
    protocol   native: the provider's tool calling. text: for a model without tool calling, the tools are described
               in the system prompt and the model writes <tool>{"name": ..., "arguments": {...}}</tool>.

Messages are kept in the Anthropic format (text, image, tool_use, tool_result blocks); the openai provider converts.
Standard library only."""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .backends import BackendError
from .harness import Harness, ToolError, image_block

MAX_TURNS = 10
MAX_TOKENS = 16000
MAX_TOOL_CHARS = 12000   # a tool result is cut here: a small local model's context is a few thousand tokens
ANTHROPIC_VERSION = '2023-06-01'
RESEARCH_TOOLS = ('guide', 'search_text', 'quest_log', 'game_state', 'runtime_state')
THINK = re.compile(r'(?s)<think>.*?(?:</think>|$)')   # reasoning some local models write into the answer

AGENT_RULES = """

四、工作方式（你在一个工具循环里：每一轮可以调用工具，拿到结果后继续，最后只写一次给玩家的回答）
- 需要查好几样东西时，先用 plan 写下 2–4 步要查什么，做完一步再用 plan 标记；打招呼和简单问题不必规划。
- 攻略原文很长、或要对照几个来源时，可以用 research 交给助手去查：它会读攻略和游戏文本，返回要点和来源网站。
- 工具出错时换一种查法或直接说明查不到，不要编造。"""

RESEARCH_SYSTEM = """你是《塞尔达传说 王国之泪》卡关助手的资料员。用工具查明交给你的问题，只依据工具结果：
- 解谜和任务做法用 guide 查攻略（神庙里或门口用 current），名称用 search_text 核对游戏里的简体中文原名。
- 返回简体中文要点，不超过 12 行：每条是一个事实或一步做法，末尾括号写来源网站名或“游戏文本”；几处来源不一致时写明。
- 不要写给玩家的客套话，不要分档，主助手会决定说多少。查不到就写“查不到”。"""

PLAN_TOOL = {'name': 'plan',
             'description': 'Write down the 2-4 things you will look up to answer, or tick off what is done. Returns the '
                            'plan as it stands. Use it for questions that need several lookups.',
             'inputSchema': {'type': 'object', 'properties': {
                 'steps': {'type': 'array', 'items': {'type': 'string'}, 'description': 'the steps, replacing the plan'},
                 'done': {'type': 'array', 'items': {'type': 'integer'}, 'description': 'numbers (from 1) of the steps done'}},
                 'additionalProperties': False}}
RESEARCH_TOOL = {'name': 'research',
                 'description': 'Hand a question to a research helper that reads the walkthroughs (guide) and the game '
                                'text with its own context and returns the facts in Chinese with their sources. Use it '
                                'when the material is long or several sources must be compared.',
                 'inputSchema': {'type': 'object', 'properties': {
                     'question': {'type': 'string', 'description': 'what to find out, e.g. 吉鲁塔古马奇神庙的宝箱怎么拿'}},
                     'required': ['question'], 'additionalProperties': False}}


def _key(settings):
    """The API key: the environment variable named in api_key_env, else the first line of api_key_file."""
    name = settings.get('api_key_env')
    if name and os.environ.get(name):
        return os.environ[name].strip()
    path = settings.get('api_key_file')
    if path:
        try:
            return Path(path).expanduser().read_text(encoding='utf-8').strip().splitlines()[0]
        except (OSError, IndexError):
            return None
    return None


def _local(url):
    return (urllib.parse.urlparse(url).hostname or '') in ('localhost', '127.0.0.1', '::1')


def sse(url, body, headers, timeout, check=None):
    """The data of each server-sent event of a streamed POST, parsed as JSON."""
    request = urllib.request.Request(url, data=json.dumps(body).encode(), method='POST',
                                     headers=dict(headers, **{'Content-Type': 'application/json; charset=utf-8',
                                                              'Accept': 'text/event-stream'}))
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read())
            error = detail.get('error') if isinstance(detail, dict) else detail
            message = error.get('message') if isinstance(error, dict) else error
        except ValueError:
            message = e.reason
        raise BackendError(f'HTTP {e.code}: {str(message)[:300]}') from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise BackendError(f'request failed: {e}') from None
    with response:
        try:
            for raw in response:
                if check:
                    check()
                line = raw.decode('utf-8', 'replace').strip()
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    return
                try:
                    yield json.loads(data)
                except ValueError:
                    continue
        except (TimeoutError, OSError) as e:
            raise BackendError(f'the stream broke off: {e}') from None


def anthropic_reply(events, on_text):
    """{"content", "stop", "usage", "model"} from the events of a streamed Anthropic message."""
    blocks, stop, usage, model = {}, None, {}, None
    for e in events:
        kind = e.get('type')
        if kind == 'message_start':
            model = (e.get('message') or {}).get('model')
            usage.update((e.get('message') or {}).get('usage') or {})
        elif kind == 'content_block_start':
            block = dict(e.get('content_block') or {})
            if block.get('type') == 'tool_use':
                block['_json'] = ''
            blocks[e.get('index', len(blocks))] = block
        elif kind == 'content_block_delta':
            block, delta = blocks.get(e.get('index')), e.get('delta') or {}
            if block is None:
                continue
            if delta.get('type') == 'text_delta':
                block['text'] = block.get('text', '') + delta.get('text', '')
                on_text(delta.get('text', ''))
            elif delta.get('type') == 'input_json_delta':
                block['_json'] += delta.get('partial_json', '')
            elif delta.get('type') == 'thinking_delta':
                block['thinking'] = block.get('thinking', '') + delta.get('thinking', '')
            elif delta.get('type') == 'signature_delta':
                block['signature'] = block.get('signature', '') + delta.get('signature', '')
        elif kind == 'message_delta':
            stop = (e.get('delta') or {}).get('stop_reason') or stop
            usage.update(e.get('usage') or {})
        elif kind == 'error':
            raise BackendError(f'the model stopped: {(e.get("error") or {}).get("message") or e}'[:300])
    content = []
    for _, block in sorted(blocks.items()):
        if block.get('type') == 'tool_use':
            raw = block.pop('_json')
            try:
                block['input'] = json.loads(raw) if raw else (block.get('input') or {})
            except ValueError:
                block['input'] = {'_invalid_json': raw}
        content.append(block)
    return {'content': content, 'stop': stop, 'usage': usage, 'model': model}


class AnthropicProvider:
    """The Anthropic Messages API, streamed."""
    name = 'anthropic'

    def __init__(self, settings):
        self.settings = settings
        self.model = settings.get('model') or 'claude-sonnet-5-5'
        self.url = (settings.get('base_url') or 'https://api.anthropic.com').rstrip('/') + '/v1/messages'
        self.vision = settings.get('vision', True)

    def available(self):
        if not _key(self.settings) and not _local(self.url):
            return False, f'no API key (set {self.settings.get("api_key_env") or "agent.api_key_env"} or agent.api_key_file)'
        return True, ''

    def body(self, system, messages, tools, tools_off):
        body = {'model': self.model, 'max_tokens': MAX_TOKENS, 'system': system, 'messages': messages, 'stream': True}
        if tools:
            body['tools'] = [{'name': t['name'], 'description': t['description'], 'input_schema': t['inputSchema']}
                             for t in tools]
            if tools_off:
                body['tool_choice'] = {'type': 'none'}
        if self.settings.get('effort'):
            body['output_config'] = {'effort': self.settings['effort']}
        return body

    def complete(self, system, messages, tools, timeout, on_text, check=None, tools_off=False):
        headers = {'anthropic-version': ANTHROPIC_VERSION}
        key = _key(self.settings)
        if key:
            headers['x-api-key'] = key
        reply = anthropic_reply(sse(self.url, self.body(system, messages, tools, tools_off), headers, timeout, check), on_text)
        reply['model'] = reply.get('model') or self.model
        return reply


class VertexProvider(AnthropicProvider):
    """Anthropic models on Vertex AI (streamRawPredict), with the vertex backend's gcloud token and its fallback model
    for a refusal."""
    name = 'vertex'

    def __init__(self, rest):
        settings = dict(rest.settings)
        settings.setdefault('model', 'claude-opus-5-5')
        super().__init__(settings)
        self.rest = rest

    def available(self):
        return self.rest.available()

    def body(self, system, messages, tools, tools_off):
        from .vertex import ANTHROPIC_VERSION as VERTEX_VERSION
        body = super().body(system, messages, tools, tools_off)
        del body['model']
        body['anthropic_version'] = VERTEX_VERSION
        return body

    def complete(self, system, messages, tools, timeout, on_text, check=None, tools_off=False):
        from .vertex import endpoint, project_and_region
        project, region = project_and_region(self.rest.config)
        while True:
            url = endpoint(project, region, self.model).replace(':rawPredict', ':streamRawPredict')
            try:
                reply = anthropic_reply(sse(url, self.body(system, messages, tools, tools_off),
                                            {'Authorization': f'Bearer {self.rest.token()}'}, timeout, check), on_text)
            except BackendError as e:
                if 'HTTP 404' in str(e):
                    raise BackendError(f'model {self.model} is not available to project {project} in {region} ({e})') from None
                raise
            fallback = self.settings.get('fallback_model')
            if reply['stop'] == 'refusal' and fallback and self.model != fallback:
                self.model = fallback   # no server-side fallback on Vertex AI: the same conversation, once, to this one
                continue
            reply['model'] = self.model
            return reply


class OpenAIProvider:
    """An OpenAI-compatible /chat/completions server, streamed, with its function calling."""
    name = 'openai'

    def __init__(self, settings):
        self.settings = settings
        self.model = settings.get('model')
        self.url = (settings.get('base_url') or 'https://api.openai.com/v1').rstrip('/') + '/chat/completions'
        self.vision = settings.get('vision', True)

    def available(self):
        if not self.model:
            return False, 'no model (agent.model)'
        if not _key(self.settings) and not _local(self.url):
            return False, f'no API key (set {self.settings.get("api_key_env") or "agent.api_key_env"} or agent.api_key_file)'
        return True, ''

    def messages(self, system, messages):
        out = [{'role': 'system', 'content': system}]
        for m in messages:
            blocks = m['content'] if isinstance(m['content'], list) else [{'type': 'text', 'text': m['content']}]
            if m['role'] == 'assistant':
                text = ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
                calls = [{'id': b['id'], 'type': 'function',
                          'function': {'name': b['name'], 'arguments': json.dumps(b.get('input') or {}, ensure_ascii=False)}}
                         for b in blocks if b.get('type') == 'tool_use']
                entry = {'role': 'assistant', 'content': text or None}
                if calls:
                    entry['tool_calls'] = calls
                out.append(entry)
                continue
            parts, images = [], []
            for b in blocks:
                if b.get('type') == 'tool_result':
                    content = b.get('content')
                    if isinstance(content, list):
                        text = '\n'.join(c.get('text', '') for c in content if c.get('type') == 'text')
                        images += [c for c in content if c.get('type') == 'image']
                    else:
                        text = str(content)
                    out.append({'role': 'tool', 'tool_call_id': b['tool_use_id'], 'content': text})
                elif b.get('type') == 'text':
                    parts.append({'type': 'text', 'text': b['text']})
                elif b.get('type') == 'image':
                    images.append(b)
            for image in images if self.vision else ():
                source = image['source']
                parts.append({'type': 'image_url', 'image_url': {'url': f'data:{source["media_type"]};base64,{source["data"]}'}})
            if parts:   # a tool's picture comes after the tool messages: the tool role carries text only
                out.append({'role': 'user', 'content': parts if any(p['type'] != 'text' for p in parts)
                            else '\n'.join(p['text'] for p in parts)})
        return out

    def complete(self, system, messages, tools, timeout, on_text, check=None, tools_off=False):
        body = {'model': self.model, 'messages': self.messages(system, messages), 'stream': True,
                'max_tokens': int(self.settings.get('max_tokens') or 4000)}
        if tools:
            body['tools'] = [{'type': 'function', 'function': {'name': t['name'], 'description': t['description'],
                                                               'parameters': t['inputSchema']}} for t in tools]
            if tools_off:
                body['tool_choice'] = 'none'
        if self.settings.get('temperature') is not None:
            body['temperature'] = self.settings['temperature']
        headers = {}
        key = _key(self.settings)
        if key:
            headers['Authorization'] = f'Bearer {key}'
        text, calls, stop, usage, model = '', {}, None, {}, None
        for e in sse(self.url, body, headers, timeout, check):
            if e.get('error'):
                raise BackendError(f'the model stopped: {e["error"]}'[:300])
            model = e.get('model') or model
            usage.update(e.get('usage') or {})
            for choice in e.get('choices') or ():
                delta = choice.get('delta') or {}
                if delta.get('content'):
                    text += delta['content']
                    on_text(delta['content'])
                for call in delta.get('tool_calls') or ():
                    slot = calls.setdefault(call.get('index', len(calls)), {'id': None, 'name': '', 'arguments': ''})
                    slot['id'] = call.get('id') or slot['id']
                    function = call.get('function') or {}
                    slot['name'] += function.get('name') or ''
                    slot['arguments'] += function.get('arguments') or ''
                stop = choice.get('finish_reason') or stop
        content = [{'type': 'text', 'text': text}] if text else []
        for _, call in sorted(calls.items()):
            try:
                arguments = json.loads(call['arguments']) if call['arguments'].strip() else {}
            except ValueError:
                arguments = {'_invalid_json': call['arguments']}
            content.append({'type': 'tool_use', 'id': call['id'] or f'call_{uuid.uuid4().hex[:12]}', 'name': call['name'],
                            'input': arguments if isinstance(arguments, dict) else {'_invalid_json': call['arguments']}})
        stop = 'tool_use' if calls else {'stop': 'end_turn', 'length': 'max_tokens'}.get(stop, stop)
        return {'content': content, 'stop': stop, 'usage': usage, 'model': model or self.model}


def make_provider(settings, config):
    kind = settings.get('provider') or 'anthropic'
    if kind == 'anthropic':
        return AnthropicProvider(settings)
    if kind == 'openai':
        return OpenAIProvider(settings)
    if kind == 'vertex':
        from .vertex import VertexREST
        rest = VertexREST(config)
        rest.settings = dict(rest.settings, **{k: v for k, v in settings.items() if k in ('model', 'effort') and v})
        return VertexProvider(rest)
    raise BackendError(f'unknown agent.provider {kind} (anthropic, openai or vertex)')


# text protocol ----------------------------------------------------------------------------------------------------------
TOOL_CALL = re.compile(r'(?s)<tool>\s*(\{.*?\})\s*</tool>')


def text_protocol_rules(tools):
    lines = ['', '', '五、工具（你所在的接口不能直接调用函数，按下面的格式写出调用）',
             '要调用工具时，这一轮只写一行：<tool>{"name": "工具名", "arguments": {参数}}</tool>，不要写别的；'
             '结果会以 <result> 发回给你。一次只调用一个工具。不再需要工具时，直接写给玩家的回答（不要带 <tool>）。']
    for t in tools:
        props = t['inputSchema'].get('properties') or {}
        args = '，'.join(f'{k}（{v.get("type", "")}{"，必填" if k in (t["inputSchema"].get("required") or ()) else ""}'
                        f'{"：" + v["description"] if v.get("description") else ""}）' for k, v in props.items())
        lines.append(f'- {t["name"]}：{t["description"]} 参数：{args or "无"}')
    return '\n'.join(lines)


def parse_text_call(text):
    """(name, arguments) of the first <tool> call in a reply, or None."""
    m = TOOL_CALL.search(text or '')
    if not m:
        return None
    try:
        call = json.loads(m.group(1))
    except ValueError:
        return ('', {'_invalid_json': m.group(1)})
    if not isinstance(call, dict):
        return ('', {'_invalid_json': m.group(1)})
    arguments = call.get('arguments')
    return str(call.get('name') or ''), arguments if isinstance(arguments, dict) else {}


def visible(text):
    """What of a reply is for the player: reasoning in <think> tags and a written tool call are not."""
    text = THINK.sub('', text or '')
    cut = text.find('<tool')
    return (text[:cut] if cut >= 0 else text).strip()


# the loop ---------------------------------------------------------------------------------------------------------------
class Agent:
    def __init__(self, provider, harness, ctx, protocol='native', max_turns=MAX_TURNS, research=True, depth=0):
        self.provider, self.harness, self.ctx = provider, harness, ctx
        self.protocol, self.max_turns, self.depth = protocol, max_turns, depth
        self.plan = []          # [[step, done]]
        self.calls = 0
        self.usage = {'input_tokens': 0, 'output_tokens': 0}
        self.tools = list(harness.tool_specs())
        if depth == 0:
            self.tools.append(PLAN_TOOL)
            if research:
                self.tools.append(RESEARCH_TOOL)

    # tools ----------------------------------------------------------------------------------------------------------
    def plan_tool(self, args):
        if isinstance(args.get('steps'), list) and args['steps']:
            self.plan = [[str(s)[:80], False] for s in args['steps'][:6]]
        for n in args.get('done') or ():
            if isinstance(n, int) and 1 <= n <= len(self.plan):
                self.plan[n - 1][1] = True
        if not self.plan:
            raise ToolError('还没有计划：用 steps 写下要查的 2–4 步')
        return {'plan': [f'{i}. [{"x" if done else " "}] {step}' for i, (step, done) in enumerate(self.plan, 1)]}

    def research_tool(self, args):
        question = str(args.get('question') or '').strip()
        if not question:
            raise ToolError('question 为空')
        helper = _ReadOnly(self.harness)
        quiet = _Quiet(self.ctx)   # the helper's notes are not the answer: only its tool calls are shown
        sub = Agent(self.provider, helper, quiet, self.protocol, max_turns=6, research=False, depth=self.depth + 1)
        result = sub.run(RESEARCH_SYSTEM, [{'type': 'text', 'text': question}])
        self.calls += sub.calls
        for k in self.usage:
            self.usage[k] += sub.usage.get(k, 0)
        return {'findings': result['text']}

    def call(self, name, args):
        """(text, image path or None, is_error) of one tool call."""
        if '_invalid_json' in args:
            return '参数不是合法的 JSON 对象，请重新调用', None, True
        try:
            if name == 'plan':
                return json.dumps(self.plan_tool(args), ensure_ascii=False), None, False
            if name == 'research' and self.depth == 0:
                return json.dumps(self.research_tool(args), ensure_ascii=False), None, False
            if name not in {t['name'] for t in self.tools}:
                return f'没有工具 {name}；可用：{"、".join(t["name"] for t in self.tools)}', None, True
            text, image = self.harness.call(name, args)
            return text, image, False
        except ToolError as e:
            return str(e), None, True
        except BackendError:
            raise
        except Exception as e:   # a tool's bug is the model's error message, not the end of the request
            return f'{type(e).__name__}: {e}', None, True

    def result_block(self, block_id, text, image, error):
        if len(text) > MAX_TOOL_CHARS:
            text = text[:MAX_TOOL_CHARS] + '…（结果太长，后面截掉了）'
        content = [{'type': 'text', 'text': text}]
        if image and getattr(self.provider, 'vision', True):
            mime, data = image_block(image)
            content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': data}})
        block = {'type': 'tool_result', 'tool_use_id': block_id, 'content': content}
        if error:
            block['is_error'] = True
        return block

    # loop -----------------------------------------------------------------------------------------------------------
    def run(self, system, content):
        """{"text", "model", "turns", "tool_calls", "usage"} for a first user message of content blocks."""
        if self.protocol == 'text':
            system = system + text_protocol_rules(self.tools)
        messages = [{'role': 'user', 'content': list(content)}]
        deadline = time.monotonic() + self.ctx.timeout
        model = None
        for turn in range(self.max_turns):
            self.ctx.check()
            remaining = deadline - time.monotonic()
            if remaining <= 3:
                raise BackendError(f'no answer within {self.ctx.timeout:.0f} s')
            last = turn == self.max_turns - 1
            if last and self.protocol == 'text':
                messages[-1]['content'].append({'type': 'text', 'text': '这是最后一轮：不要再调用工具，直接写给玩家的回答。'})
            written = {'text': ''}

            def on_text(delta):
                written['text'] += delta
                shown = visible(written['text'])
                if shown:
                    self.ctx.event('text', shown)
            reply = self.provider.complete(system, messages, None if self.protocol == 'text' else self.tools,
                                           min(remaining, 180), on_text, self.ctx.check, tools_off=last)
            model = reply.get('model') or model
            for k in self.usage:
                self.usage[k] += int((reply.get('usage') or {}).get(k) or 0)
            blocks = reply['content']
            messages.append({'role': 'assistant', 'content': blocks})
            text = ''.join(b.get('text', '') for b in blocks if b.get('type') == 'text')
            if self.protocol == 'text':
                call = None if last else parse_text_call(text)
                if call:
                    name, args = call
                    self.calls += 1
                    self.ctx.event('tool', name)
                    result, image, error = self.call(name, args)
                    messages[-1]['content'] = [{'type': 'text', 'text': TOOL_CALL.search(text).group(0)}]
                    shown = f'<result name="{name}"{" error" if error else ""}>\n{result[:MAX_TOOL_CHARS]}\n</result>'
                    user = [{'type': 'text', 'text': shown}]
                    if image and getattr(self.provider, 'vision', True):
                        mime, data = image_block(image)
                        user.append({'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': data}})
                    messages.append({'role': 'user', 'content': user})
                    continue
            elif reply['stop'] == 'tool_use' and not last:
                results = []
                for block in blocks:
                    if block.get('type') == 'tool_use':
                        self.calls += 1
                        self.ctx.event('tool', block.get('name'))
                        results.append(self.result_block(block['id'], *self.call(block.get('name'), block.get('input') or {})))
                messages.append({'role': 'user', 'content': results})   # every result of the turn in one message
                continue
            answer = visible(text)
            if not answer:
                if reply['stop'] == 'refusal':
                    raise BackendError('the model declined this request')
                raise BackendError(f'the model wrote no answer (stop reason {reply["stop"]})')
            return {'text': answer, 'model': model, 'turns': turn + 1, 'tool_calls': self.calls, 'usage': self.usage}
        raise BackendError(f'no answer after {self.max_turns} rounds')


class _ReadOnly:
    """The research helper's tools: the harness's read-only lookups, sharing its loaded tables."""

    def __init__(self, harness):
        self.harness = harness

    def tool_specs(self):
        return [s for s in self.harness.tool_specs() if s['name'] in RESEARCH_TOOLS]

    def call(self, name, arguments=None):
        if name not in RESEARCH_TOOLS:
            raise ToolError(f'资料员只能查资料：{"、".join(RESEARCH_TOOLS)}')
        return self.harness.call(name, arguments)


class _Quiet:
    """A run context for a sub-agent: the same budget and cancel, the tool events, none of its text."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.timeout = max(5.0, ctx.timeout * 0.6)

    def check(self):
        self.ctx.check()

    def event(self, kind, value):
        if kind == 'tool':
            self.ctx.event('tool', value)


def run(provider, system, prompt, ctx, config, settings=None):
    """One hint through the agent loop: the backend's run()."""
    settings = settings or {}
    harness = Harness(config, ctx.romfs, ctx.save_root, ctx.allow_screenshot, ctx.allow_actions, ctx.marks, ctx.scene_size,
                      memory=ctx.memory_path)
    content = [{'type': 'text', 'text': prompt}]
    if ctx.scene_image and getattr(provider, 'vision', True):
        mime, data = image_block(ctx.scene_image)
        content.insert(0, {'type': 'image', 'source': {'type': 'base64', 'media_type': mime, 'data': data}})
    agent = Agent(provider, harness, ctx, settings.get('tool_protocol') or 'native',
                  int(settings.get('max_turns') or MAX_TURNS), settings.get('research', True))
    return agent.run(system + AGENT_RULES, content)


class AgentBackend:
    """The 'agent' backend: assistant.json "agent" names the provider and the model."""
    name = 'agent'
    title = '内置智能体'

    def __init__(self, config):
        self.config = config
        self.settings = config.get('agent') or {}

    def provider(self):
        return make_provider(self.settings, self.config)

    def available(self):
        if not self.settings.get('model') and (self.settings.get('provider') or 'anthropic') != 'vertex':
            return False, 'no model set (assistant.json agent.model)'
        try:
            return self.provider().available()
        except BackendError as e:
            return False, str(e)

    def run(self, system, prompt, ctx):
        provider = self.provider()
        try:
            result = run(provider, system, prompt, ctx, self.config, self.settings)
        except BackendError as e:
            raise BackendError(f'{self.title}（{provider.name} {getattr(provider, "model", "")}）: {e}') from None
        return result

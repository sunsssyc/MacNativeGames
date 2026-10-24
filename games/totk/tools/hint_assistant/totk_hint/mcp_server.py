"""totk-harness: the harness tools as a Model Context Protocol server over stdio (newline-delimited JSON-RPC 2.0).

Only the part of MCP a tool server needs: initialize, ping, tools/list, tools/call (text results; the screenshot tool
also returns the picture as image content). Claude Code (--mcp-config) and Codex (-c mcp_servers.totk-harness.*) start
it as `python3.14 run.py mcp`."""
import json
import sys
import time

from . import __version__
from .harness import Harness, ToolError, image_block

INSTRUCTIONS = ('The player\'s Tears of the Kingdom game: the newest save and the game\'s own quest log (history, not '
                'the live game), live runtime state, place and item names (Simplified Chinese). Call only the tools a '
                'question needs; search_text checks names and facts. Game inputs (press_button) are offered only when '
                'the player allowed this request to act.')
WRITES = ('screenshot', 'press_button', 'stop_action', 'mark_screen')   # not read-only: they reach into the game


def _error(id_, code, message):
    return {'jsonrpc': '2.0', 'id': id_, 'error': {'code': code, 'message': message}}


def _result(id_, result):
    return {'jsonrpc': '2.0', 'id': id_, 'result': result}


class Server:
    def __init__(self, harness, log=None):
        self.harness = harness
        self.log = log or (lambda text: print(text, file=sys.stderr, flush=True))

    def handle(self, message):
        """The response to one JSON-RPC message, or None for a notification."""
        if not isinstance(message, dict) or message.get('jsonrpc') != '2.0' or 'method' not in message:
            return _error(message.get('id') if isinstance(message, dict) else None, -32600, 'invalid request')
        method, id_, params = message['method'], message.get('id'), message.get('params') or {}
        if not isinstance(method, str) or not isinstance(params, dict):
            return _error(id_, -32602, 'method must be a string and params an object')
        if id_ is None:   # notifications: initialized, cancelled, ...
            return None
        if method == 'initialize':
            version = params.get('protocolVersion')
            return _result(id_, {
                'protocolVersion': version if isinstance(version, str) and version else '2025-06-18',
                'capabilities': {'tools': {'listChanged': False}},
                'serverInfo': {'name': 'totk-harness', 'version': __version__},
                'instructions': INSTRUCTIONS})
        if method == 'ping':
            return _result(id_, {})
        if method == 'tools/list':
            tools = [dict(spec, annotations={'readOnlyHint': spec['name'] not in WRITES, 'openWorldHint': False})
                     for spec in self.harness.tool_specs()]
            return _result(id_, {'tools': tools})
        if method in ('resources/list', 'prompts/list', 'resources/templates/list'):
            return _result(id_, {method.split('/')[0] if method != 'resources/templates/list' else 'resourceTemplates': []})
        if method == 'tools/call':
            if not isinstance(params.get('arguments', {}), dict):
                return _error(id_, -32602, 'arguments must be an object')
            name = params.get('name')
            if not isinstance(name, str) or name not in {spec['name'] for spec in self.harness.tool_specs()}:
                return _error(id_, -32602, f'unknown tool: {name}')
            t0 = time.monotonic()
            try:
                text, image = self.harness.call(name, params.get('arguments') or {})
                content = [{'type': 'text', 'text': text}]
                if image:
                    mime, data = image_block(image)
                    content.append({'type': 'image', 'data': data, 'mimeType': mime})
                result = {'content': content, 'isError': False}
            except ToolError as e:
                result = {'content': [{'type': 'text', 'text': str(e)}], 'isError': True}
            except Exception as e:   # a reader bug must not take the server down: report it to the model
                result = {'content': [{'type': 'text', 'text': f'{type(e).__name__}: {e}'}], 'isError': True}
            self.log(f'[totk-harness] {name} {json.dumps(params.get("arguments") or {}, ensure_ascii=False)} '
                     f'{"error" if result["isError"] else "ok"} {time.monotonic() - t0:.2f}s')
            return _result(id_, result)
        return _error(id_, -32601, f'method not found: {method}')

    def run(self, stdin=None, stdout=None):
        stdin = stdin or sys.stdin.buffer
        stdout = stdout or sys.stdout.buffer
        for raw in stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                responses = [_error(None, -32700, 'parse error')]
            else:
                batch = message if isinstance(message, list) else [message]
                responses = [r for r in (self.handle(m) for m in batch) if r is not None]
            for response in responses:
                stdout.write(json.dumps(response, ensure_ascii=False).encode() + b'\n')
            stdout.flush()


def main(args):
    scene_size = tuple(int(v) for v in args.scene_size.split('x')) if args.scene_size else None
    harness = Harness(romfs=args.romfs, save_root=args.save_root, allow_screenshot=args.allow_screenshot,
                      allow_actions=args.allow_actions, marks=args.marks, scene_size=scene_size, config=args.config_data)
    Server(harness).run()
    return 0

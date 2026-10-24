"""The models that answer: the agents already installed on this Mac first, then Vertex AI.

    claude-code          Claude Code headless (claude -p) with the totk-harness MCP server
    codex                Codex (codex exec) with the same MCP server, given per run (-c mcp_servers.totk-harness.*);
                         the user's ~/.codex/config.toml is not read (--ignore-user-config) and never written
    vertex-claude-code   Claude Code with its Vertex AI provider (CLAUDE_CODE_USE_VERTEX=1)
    vertex               Anthropic models on Vertex AI over REST (vertex.py), for Macs without Claude Code

"auto" tries assistant.json "backends" in order and takes the first answer."""
import glob
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from . import tables as tablemod

RUN_PY = Path(__file__).resolve().parents[1] / 'run.py'
TOOLS = ('wait_state', 'runtime_state', 'game_state', 'quest_log', 'search_text')
ACTION_TOOLS = ('press_button', 'press_sequence', 'stop_action')   # only for a request the player allowed to act (Context.allow_actions)
CODEX_FEATURES_OFF = ('apps', 'browser_use', 'browser_use_external', 'computer_use', 'image_generation', 'in_app_browser',
                      'plugins', 'remote_plugin', 'hooks', 'goals', 'memories')


class BackendError(Exception):
    pass


class Cancelled(Exception):
    pass


class Context:
    """What one hint run needs besides the prompt."""

    def __init__(self, config, allow_screenshot=False, romfs=None, save_root=None, cancel=None, timeout=None,
                 allow_actions=False, on_event=None):
        self.config = config
        self.scene_image = None
        self.allow_screenshot = allow_screenshot
        self.allow_actions = allow_actions
        self.on_event = on_event   # ('tool', tool name) when a tool starts; ('text', answer so far) as it is written
        self.scene_size = None     # with scene_image: (width, height), and mark_screen is offered (指给我看)
        self.romfs = romfs
        self.save_root = save_root
        self.cancel = cancel   # a threading.Event, or None
        self.timeout = timeout or config.get('timeout_seconds') or 120
        self.workdir = tablemod.CACHE_ROOT / 'runs' / uuid.uuid4().hex[:12]

    @property
    def marks(self):
        """Where mark_screen writes this run's marks, when it is offered."""
        return self.workdir / 'marks.json' if self.scene_size else None

    def mcp_command(self):
        """The command that starts the totk-harness MCP server for this run."""
        args = ['-E', '-s', str(RUN_PY), 'mcp']
        if self.marks:
            args += ['--marks', str(self.marks), '--scene-size', '%dx%d' % self.scene_size]
        if self.allow_screenshot:
            args.append('--allow-screenshot')
        if self.allow_actions:
            args.append('--allow-actions')
        if self.romfs:
            args += ['--romfs', str(self.romfs)]
        if self.save_root:
            args += ['--save-root', str(self.save_root)]
        if self.config.get('_path'):
            args += ['--config', self.config['_path']]
        return sys.executable, args

    def check(self):
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled()

    def event(self, kind, value):
        if self.on_event:
            try:
                self.on_event(kind, value)
            except Exception:   # progress is cosmetic: it never fails the hint
                pass


def tool_name(name):
    """game_state from mcp__totk-harness__game_state (Claude Code) or totk-harness.game_state."""
    return str(name or '').replace('.', '__').split('__')[-1]


def run_process(args, ctx, stdin_text='', env=None, cwd=None, on_line=None):
    """(exit status, stdout, stderr) of a command, stopped at ctx.timeout or when ctx.cancel is set (the whole process
    group: the agent and the MCP server it started). on_line gets each line of standard output as it is written."""
    ctx.check()
    try:
        p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                             cwd=cwd, start_new_session=True)
    except OSError as e:
        raise BackendError(f'{args[0]} did not start: {e}') from None
    deadline = time.monotonic() + ctx.timeout
    lines, out, err = queue.Queue(), [], []

    def read(stream, into, forward):
        for raw in stream:
            into.append(raw)
            if forward:
                lines.put(raw.decode('utf-8', 'replace'))
        stream.close()
    readers = [threading.Thread(target=read, args=(p.stdout, out, True), daemon=True),
               threading.Thread(target=read, args=(p.stderr, err, False), daemon=True)]
    for r in readers:
        r.start()
    try:
        p.stdin.write(stdin_text.encode())
        p.stdin.close()
    except OSError:   # it exited before reading its input: the exit status says why
        pass
    stop, exited = None, None
    while True:
        try:
            line = lines.get(timeout=0.2)
        except queue.Empty:
            line = None
        if line is not None and on_line:
            on_line(line)
        if p.poll() is not None:   # done once its output is read (a grandchild holding the pipe gets 2 s)
            exited = exited or time.monotonic()
            if lines.empty() and (not readers[0].is_alive() or time.monotonic() - exited > 2):
                break
            continue
        stop = 'cancelled' if ctx.cancel is not None and ctx.cancel.is_set() else 'timeout' if time.monotonic() > deadline else None
        if stop:
            break
    if stop:
        for sig, wait in ((signal.SIGTERM, 3), (signal.SIGKILL, 3)):
            try:
                os.killpg(p.pid, sig)
            except ProcessLookupError:
                break
            try:
                p.wait(wait)
                break
            except subprocess.TimeoutExpired:
                pass
    p.wait()
    for r in readers:
        r.join(2)
    if stop == 'cancelled':
        raise Cancelled()
    if stop:
        raise BackendError(f'{Path(args[0]).name} did not answer within {ctx.timeout:.0f} s')
    return p.returncode, b''.join(out).decode('utf-8', 'replace'), b''.join(err).decode('utf-8', 'replace')


def find_binary(name, configured=None, extra=()):
    """configured path, then PATH, then the usual install locations (a Finder-started app has a minimal PATH)."""
    candidates = [configured] if configured else []
    for folder in os.environ.get('PATH', '').split(':'):
        if folder:
            candidates.append(os.path.join(folder, name))
    candidates += [str(Path(p).expanduser()) for p in extra]
    for c in candidates:
        for path in sorted(glob.glob(os.path.expanduser(c)), reverse=True) if any(ch in c for ch in '*?') else [os.path.expanduser(c)]:
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path
    return None


def tool_env(binary):
    """The environment for an agent: PATH also holds the agent's own folder (an npm-installed codex needs its node)."""
    env = dict(os.environ)
    folder = str(Path(binary).parent)
    env['PATH'] = ':'.join([folder] + [p for p in env.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin').split(':') if p != folder])
    return env


class ClaudeCode:
    name = 'claude-code'
    title = 'Claude Code'

    def __init__(self, config, vertex=False):
        self.config = config
        self.vertex = vertex
        if vertex:
            self.name, self.title = 'vertex-claude-code', 'Claude Code（Vertex AI）'
        self.settings = config.get('claude_code') or {}

    def binary(self):
        return find_binary('claude', self.settings.get('path'),
                           ('~/.local/bin/claude', '~/.claude/local/claude', '/opt/homebrew/bin/claude', '/usr/local/bin/claude'))

    def available(self):
        if not self.binary():
            return False, 'Claude Code (claude) is not installed'
        if self.vertex:
            from .vertex import project_and_region
            project, _ = project_and_region(self.config)
            if not project:
                return False, 'no Google Cloud project (assistant.json vertex.project or gcloud config)'
            adc = Path(os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') or
                       '~/.config/gcloud/application_default_credentials.json').expanduser()
            if not adc.is_file():
                return False, 'no Google application default credentials (gcloud auth application-default login)'
        return True, ''

    def run(self, system, prompt, ctx):
        binary = self.binary()
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        python, args = ctx.mcp_command()
        mcp = {'mcpServers': {'totk-harness': {'type': 'stdio', 'command': python, 'args': args}}}
        mcp_file = ctx.workdir / 'mcp.json'
        mcp_file.write_text(json.dumps(mcp, ensure_ascii=False))
        tools = [f'mcp__totk-harness__{t}' for t in TOOLS + (ACTION_TOOLS if ctx.allow_actions else ())
                 + (('mark_screen',) if ctx.marks else ())]
        builtin = ''
        # stream-json with partial messages: the answer is shown as it is written, tool calls as they start
        command = [binary, '-p', '--output-format', 'stream-json', '--verbose', '--include-partial-messages',
                   '--system-prompt', system, '--mcp-config', str(mcp_file),
                   '--strict-mcp-config', '--permission-mode', 'dontAsk', '--no-session-persistence',
                   '--setting-sources', 'project']
        if ctx.allow_screenshot:
            from .harness import SHOTS
            SHOTS.mkdir(parents=True, exist_ok=True)
            tools += ['mcp__totk-harness__screenshot', f'Read(/{SHOTS}/**)']
            builtin = 'Read'
            command += ['--add-dir', str(SHOTS)]
        if ctx.scene_image:
            builtin = 'Read'
            tools += [f'Read(/{ctx.scene_image})']
            command += ['--add-dir', str(ctx.scene_image.parent)]
            prompt = f'先用 Read 查看本次游戏窗口截图：{ctx.scene_image}\n' + prompt
        command += ['--tools', builtin, '--allowedTools', ','.join(tools)]
        env = tool_env(binary)
        if self.vertex:
            from .vertex import project_and_region
            project, region = project_and_region(self.config)
            v = self.config.get('vertex') or {}
            env.update(CLAUDE_CODE_USE_VERTEX='1', ANTHROPIC_VERTEX_PROJECT_ID=project, CLOUD_ML_REGION=region)
            model, effort = v.get('model'), v.get('effort')
        else:
            model, effort = self.settings.get('model'), self.settings.get('effort')
        if model:
            command += ['--model', model]
        if effort:
            command += ['--effort', effort]
        stream = {'text': '', 'result': {}}

        def line(raw):
            try:
                event = json.loads(raw)
            except ValueError:
                return
            if event.get('type') == 'result':
                stream['result'] = event
            if event.get('type') != 'stream_event':
                return
            e = event.get('event') or {}
            block = e.get('content_block') or {}
            if e.get('type') == 'message_start':
                stream['text'] = ''
            elif e.get('type') == 'content_block_start' and block.get('type') == 'tool_use':
                stream['text'] = ''   # words before a tool call were not the answer
                ctx.event('tool', tool_name(block.get('name')))
            elif e.get('type') == 'content_block_delta' and (e.get('delta') or {}).get('type') == 'text_delta':
                stream['text'] += e['delta'].get('text') or ''
                ctx.event('text', stream['text'])
        code, out, err = run_process(command, ctx, prompt, env, str(ctx.workdir), line)
        result = stream['result']
        if code != 0 or result.get('is_error') or not result.get('result'):
            detail = result.get('result') or result.get('subtype') or (err.strip().splitlines() or out.strip().splitlines() or [''])[-1]
            raise BackendError(f'{self.title} failed (exit {code}): {detail[:300]}')
        return {'text': result['result'], 'model': model or 'default', 'turns': result.get('num_turns'),
                'cost_usd': result.get('total_cost_usd')}


class Codex:
    name = 'codex'
    title = 'Codex'
    _features = {}
    _checked = {}   # (path, mtime) -> starts: the service asks every request, a codex --version takes a second or more

    def __init__(self, config):
        self.config = config
        self.settings = config.get('codex') or {}

    def _works(self, path):
        key = (path, os.stat(path).st_mtime_ns)
        if key not in self._checked:
            try:
                r = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=20, env=tool_env(path))
                self._checked[key] = r.returncode == 0 and 'codex' in (r.stdout + r.stderr).lower()
            except (OSError, subprocess.TimeoutExpired):
                return False   # not remembered: a slow first start is no reason to skip codex for the whole session
        return self._checked[key]

    def binary(self):
        """A codex that actually starts: an npm install can lack its native binary, so each candidate is tried."""
        candidates = [self.settings.get('path')] if self.settings.get('path') else []
        candidates += [os.path.join(p, 'codex') for p in os.environ.get('PATH', '').split(':') if p]
        candidates += sorted(glob.glob(os.path.expanduser('~/.nvm/versions/node/*/bin/codex')), reverse=True)
        candidates += ['/opt/homebrew/bin/codex', '/usr/local/bin/codex', os.path.expanduser('~/.local/bin/codex'),
                       '/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex',
                       '/Applications/Codex.app/Contents/Resources/codex-cli/bin/codex']
        seen = set()
        for path in candidates:
            path = os.path.expanduser(path)
            if path in seen or not (os.path.isfile(path) and os.access(path, os.X_OK)):
                continue
            seen.add(path)
            if self._works(path):
                return path
        return None

    def available(self):
        return (True, '') if self.binary() else (False, 'no working Codex CLI (codex) found')

    def features_off(self, binary):
        """The features to switch off that this codex has and has on (an unknown name makes codex exit)."""
        if binary not in self._features:
            try:
                listed = subprocess.run([binary, 'features', 'list'], capture_output=True, text=True, timeout=20,
                                        env=tool_env(binary)).stdout
            except (OSError, subprocess.TimeoutExpired):
                listed = ''
            on = {line.split()[0] for line in listed.splitlines() if line.split() and line.split()[-1] == 'true'}
            self._features[binary] = [f for f in CODEX_FEATURES_OFF if f in on]
        return self._features[binary]

    def run(self, system, prompt, ctx):
        binary = self.binary()
        if not binary:
            raise BackendError('no working Codex CLI (codex) found')
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        python, args = ctx.mcp_command()
        last = ctx.workdir / 'answer.txt'

        def toml(value):
            return json.dumps(value, ensure_ascii=False)   # JSON strings and string arrays are valid TOML
        command = [binary, 'exec', '--ignore-user-config', '--skip-git-repo-check', '--ephemeral', '-s', 'read-only',
                   '--json', '--color', 'never', '-C', str(ctx.workdir), '-o', str(last),
                   '-c', f'mcp_servers.totk-harness.command={toml(python)}',
                   '-c', f'mcp_servers.totk-harness.args={toml(args)}',
                   '-c', 'mcp_servers.totk-harness.startup_timeout_sec=30',
                   '-c', 'mcp_servers.totk-harness.tool_timeout_sec=60']
        for feature in self.features_off(binary):
            command += ['--disable', feature]
        if self.settings.get('effort'):
            command += ['-c', f'model_reasoning_effort={toml(self.settings["effort"])}']
        if self.settings.get('model'):
            command += ['-m', self.settings['model']]
        if ctx.scene_image:
            command += ['--image', str(ctx.scene_image)]
        command.append('-')   # the prompt from standard input
        def line(raw):   # codex exec --json: one event per line; its messages arrive whole
            try:
                event = json.loads(raw)
            except ValueError:
                return
            item = event.get('item') or {}
            if event.get('type') == 'item.started' and item.get('type') == 'mcp_tool_call':
                ctx.event('tool', tool_name(item.get('tool')))
            elif event.get('type') == 'item.completed' and item.get('type') == 'agent_message' and item.get('text'):
                ctx.event('text', item['text'])
        code, out, err = run_process(command, ctx, f'{system}\n\n{prompt}', tool_env(binary), str(ctx.workdir), line)
        text = last.read_text(encoding='utf-8').strip() if last.is_file() else ''
        if code != 0 or not text:
            lines = [l for l in (err + '\n' + out).splitlines() if l.strip()]
            raise BackendError(f'Codex failed (exit {code}): {(lines[-1] if lines else "no answer")[:300]}')
        return {'text': text, 'model': self.settings.get('model') or 'default'}


def make(name, config):
    if name == 'claude-code':
        return ClaudeCode(config)
    if name == 'vertex-claude-code':
        return ClaudeCode(config, vertex=True)
    if name == 'codex':
        return Codex(config)
    if name == 'vertex':
        from .vertex import VertexREST
        return VertexREST(config)
    raise BackendError(f'unknown backend {name} (choose from auto, claude-code, codex, vertex-claude-code, vertex)')


def order(name, config):
    if name in (None, '', 'auto'):
        return [n for n in config.get('backends') or () if n in ('claude-code', 'codex', 'vertex-claude-code', 'vertex')]
    return [name]


def report(config):
    """[(backend, available, reason)] for every backend."""
    out = []
    for name in ('claude-code', 'codex', 'vertex-claude-code', 'vertex'):
        try:
            ok, why = make(name, config).available()
        except Exception as e:
            ok, why = False, f'{type(e).__name__}: {e}'
        out.append((name, ok, why))
    return out


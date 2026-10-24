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
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from . import tables as tablemod

RUN_PY = Path(__file__).resolve().parents[1] / 'run.py'
TOOLS = ('wait_state', 'runtime_state', 'press_button', 'stop_action', 'game_state', 'quest_log', 'search_text')
CODEX_FEATURES_OFF = ('apps', 'browser_use', 'browser_use_external', 'computer_use', 'image_generation', 'in_app_browser',
                      'plugins', 'remote_plugin', 'hooks', 'goals', 'memories')


class BackendError(Exception):
    pass


class Cancelled(Exception):
    pass


class Context:
    """What one hint run needs besides the prompt."""

    def __init__(self, config, allow_screenshot=False, romfs=None, save_root=None, cancel=None, timeout=None):
        self.config = config
        self.scene_image = None
        self.allow_screenshot = allow_screenshot
        self.romfs = romfs
        self.save_root = save_root
        self.cancel = cancel   # a threading.Event, or None
        self.timeout = timeout or config.get('timeout_seconds') or 120
        self.workdir = tablemod.CACHE_ROOT / 'runs' / uuid.uuid4().hex[:12]

    def mcp_command(self):
        """The command that starts the totk-harness MCP server for this run."""
        args = ['-E', '-s', str(RUN_PY), 'mcp']
        if self.allow_screenshot:
            args.append('--allow-screenshot')
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


def run_process(args, ctx, stdin_text='', env=None, cwd=None):
    """(exit status, stdout, stderr) of a command, stopped at ctx.timeout or when ctx.cancel is set (the whole process
    group: the agent and the MCP server it started)."""
    ctx.check()
    try:
        p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                             cwd=cwd, start_new_session=True)
    except OSError as e:
        raise BackendError(f'{args[0]} did not start: {e}') from None
    deadline = time.monotonic() + ctx.timeout
    data = stdin_text.encode()
    while True:
        try:
            out, err = p.communicate(data, timeout=0.5)
            return p.returncode, out.decode('utf-8', 'replace'), err.decode('utf-8', 'replace')
        except subprocess.TimeoutExpired:
            data = None
            stop = 'cancelled' if ctx.cancel is not None and ctx.cancel.is_set() else 'timeout' if time.monotonic() > deadline else None
            if not stop:
                continue
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
            p.communicate()
            if stop == 'cancelled':
                raise Cancelled()
            raise BackendError(f'{Path(args[0]).name} did not answer within {ctx.timeout:.0f} s')


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
        tools = [f'mcp__totk-harness__{t}' for t in TOOLS]
        builtin = ''
        command = [binary, '-p', '--output-format', 'json', '--system-prompt', system, '--mcp-config', str(mcp_file),
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
        code, out, err = run_process(command, ctx, prompt, env, str(ctx.workdir))
        try:
            result = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
        except ValueError:
            result = {}
        if code != 0 or result.get('is_error') or not result.get('result'):
            detail = result.get('result') or result.get('subtype') or (err.strip().splitlines() or out.strip().splitlines() or [''])[-1]
            raise BackendError(f'{self.title} failed (exit {code}): {detail[:300]}')
        return {'text': result['result'], 'model': model or 'default', 'turns': result.get('num_turns'),
                'cost_usd': result.get('total_cost_usd')}


class Codex:
    name = 'codex'
    title = 'Codex'
    _features = {}

    def __init__(self, config):
        self.config = config
        self.settings = config.get('codex') or {}

    def _works(self, path):
        try:
            r = subprocess.run([path, '--version'], capture_output=True, text=True, timeout=20, env=tool_env(path))
            return r.returncode == 0 and 'codex' in (r.stdout + r.stderr).lower()
        except (OSError, subprocess.TimeoutExpired):
            return False

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
                   '--color', 'never', '-C', str(ctx.workdir), '-o', str(last),
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
        code, out, err = run_process(command, ctx, f'{system}\n\n{prompt}', tool_env(binary), str(ctx.workdir))
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


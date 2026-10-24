"""assistant.json: the stuck helper's settings, next to the game's other files
(~/Library/Application Support/MacNativeGames/TOTK/assistant.json). Every key is optional; missing keys take the
defaults below. The file holds no secrets: Claude Code, Codex and gcloud keep their own sign-in."""
import copy
import json
from pathlib import Path

from .romfs import DATA_DIR

PATH = DATA_DIR / 'assistant.json'
BACKENDS = ('claude-code', 'codex', 'vertex-claude-code', 'vertex', 'agent')
DEFAULTS = {
    'enabled': False,             # the game's launcher starts the hint service (serve) only when true
    'backends': list(BACKENDS),   # "auto" tries these in order until one answers
    'tier_default': 1,            # the first press of key 8: 1 where to go, 2 what to use, 3 full solution
    'observe_current_scene': False,  # explicit opt-in; one game window image per question
    # may the model look at the game window: the frame comes from the game itself (no macOS screen recording), and
    # behind the open panel it is the paused frame the panel opened on (user, 2026-10-24: no permission gate needed)
    'allow_screenshot': True,
    # May the model press game buttons. Even when true, only for a question the player sends with 「允许操作」 in the
    # panel; the game takes at most a few presses per request and Esc stops them (runtime/hint_runtime_tools.inc).
    'allow_actions': False,
    'timeout_seconds': 45,        # per backend: a stuck one leaves time for the next in "backends"
    'total_timeout_seconds': 150, # one request, all backends; the game gives up a little after this
    'prefetch_state': False,      # legacy key; observations are now tool-selected
    'romfs': None,                # game data folder (romfs.bin + runtime-index.bin or index.json); found by itself
    'save_root': None,            # folder with <user id>/slot_NN; default: the player's profile
    'text_language': 'CNzh',      # game text language for names and quest logs
    # 朗读 (voice.py): read answers aloud, line by line as they are written. Off by default (the panel's 朗读 button).
    # engine "auto": the local Qwen3-TTS clone once installed with a recorded reference, else Google Chirp 3 HD with the
    # gcloud sign-in (free up to 1 million characters a month; google_monthly_chars stops short of that), else the
    # macOS system voice. "local" also shows the panel's 下载语音 / 录我的声音; "google" and "system" use only that one.
    'voice': {'enabled': False, 'engine': 'auto', 'google_voice': 'cmn-CN-Chirp3-HD-Leda', 'google_monthly_chars': 900_000,
              'unload_after_seconds': 120},
    # web: Claude Code may also search the web (WebSearch / WebFetch) for what the guide tool does not cover
    'claude_code': {'path': None, 'model': 'opus', 'effort': 'low', 'web': True},
    # guide (guides.py): shrine and quest walkthroughs from Zelda Wiki, Samurai Gamers and IGN, for every backend
    'guides': {'enabled': True, 'timeout': 8},
    'codex': {'path': None, 'model': None, 'effort': 'low'},
    # Vertex AI: Claude Code with its Vertex provider (vertex-claude-code) and the direct REST client (vertex)
    # credentials: a service account key or authorized-user JSON file to sign in with instead of gcloud (its path only;
    # the file stays where it is and is never copied)
    'vertex': {'project': None, 'region': 'global', 'model': 'claude-opus-5-5', 'effort': 'low',
               'fallback_model': 'claude-opus-4-8', 'gcloud': None, 'credentials': None},
    # agent: the assistant's own agent loop (agent.py) with a plain model. provider "anthropic" (Messages API),
    # "openai" (any OpenAI-compatible server; base_url e.g. http://localhost:11434/v1 for Ollama needs no key),
    # "vertex" (Anthropic models on Vertex AI) or "gemini" (Gemini on Vertex AI, default gemini-4-argon; vertex.credentials
    # or gcloud signs in). The key comes from the environment variable api_key_env or the file api_key_file, never this file.
    # tool_protocol "text" for a model without function calling; vision false for one that takes no pictures.
    'agent': {'provider': 'anthropic', 'model': None, 'base_url': None, 'api_key_env': 'ANTHROPIC_API_KEY',
              'api_key_file': None, 'effort': None, 'tool_protocol': 'native', 'vision': True, 'max_turns': 10,
              'research': True},
    # memory (memory.py): earlier answers and the model's notes about the player, in assistant-memory.json
    'memory': {'enabled': True},
}


def _merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load(path=None):
    """The effective settings: DEFAULTS overlaid with the file (a missing file is fine, a broken one is an error)."""
    path = Path(path) if path else PATH
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except ValueError as e:
            raise ValueError(f'{path}: not valid JSON ({e})') from None
        if not isinstance(data, dict):
            raise ValueError(f'{path}: expected a JSON object')
    config = _merge(DEFAULTS, data)
    config['_path'] = str(path)
    for key in ('enabled', 'allow_screenshot', 'allow_actions', 'observe_current_scene', 'prefetch_state'):
        if not isinstance(config[key], bool):
            raise ValueError(f'{path}: {key} must be true or false')
    if not isinstance(config['backends'], list) or any(name not in BACKENDS for name in config['backends']):
        raise ValueError(f'{path}: backends must be a list from {BACKENDS}')
    for key in ('timeout_seconds', 'total_timeout_seconds'):
        timeout = config[key]
        if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not 1 <= timeout <= 600:
            raise ValueError(f'{path}: {key} must be between 1 and 600')
    for key in ('claude_code', 'codex', 'vertex', 'voice', 'agent', 'memory', 'guides'):
        if not isinstance(config[key], dict):
            raise ValueError(f'{path}: {key} must be an object')
    voice = config['voice']
    if not isinstance(voice.get('enabled'), bool):
        raise ValueError(f'{path}: voice.enabled must be true or false')
    if voice.get('engine') not in ('auto', 'local', 'google', 'system'):
        raise ValueError(f'{path}: voice.engine must be auto, local, google or system')
    chars = voice.get('google_monthly_chars')
    if isinstance(chars, bool) or not isinstance(chars, int) or chars < 0:
        raise ValueError(f'{path}: voice.google_monthly_chars must be a whole number of characters')
    agent = config['agent']
    if agent.get('provider') not in ('anthropic', 'openai', 'vertex', 'gemini'):
        raise ValueError(f'{path}: agent.provider must be anthropic, openai, vertex or gemini')
    if agent.get('tool_protocol') not in ('native', 'text'):
        raise ValueError(f'{path}: agent.tool_protocol must be native or text')
    tier = config.get('tier_default')
    config['tier_default'] = tier if tier in (1, 2, 3) else 1
    return config


def write_default(path=None):
    """Write a settings file with the defaults (never overwrites)."""
    path = Path(path) if path else PATH
    if path.exists():
        raise FileExistsError(f'{path} already exists')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path

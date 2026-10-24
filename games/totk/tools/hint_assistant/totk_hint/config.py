"""assistant.json: the stuck helper's settings, next to the game's other files
(~/Library/Application Support/MacNativeGames/TOTK/assistant.json). Every key is optional; missing keys take the
defaults below. The file holds no secrets: Claude Code, Codex and gcloud keep their own sign-in."""
import copy
import json
from pathlib import Path

from .romfs import DATA_DIR

PATH = DATA_DIR / 'assistant.json'
BACKENDS = ('claude-code', 'codex', 'vertex-claude-code', 'vertex')
DEFAULTS = {
    'enabled': False,             # the game's launcher starts the hint service (serve) only when true
    'backends': list(BACKENDS),   # "auto" tries these in order until one answers
    'tier_default': 1,            # the first press of key 8: 1 where to go, 2 what to use, 3 full solution
    'observe_current_scene': False,  # explicit opt-in; one game window image per question
    'allow_screenshot': False,    # may the model look at the game window (the player opts in here)
    'timeout_seconds': 120,       # per backend
    'prefetch_state': False,      # legacy key; observations are now tool-selected
    'romfs': None,                # game data folder (romfs.bin + runtime-index.bin or index.json); found by itself
    'save_root': None,            # folder with <user id>/slot_NN; default: the player's profile
    'text_language': 'CNzh',      # game text language for names and quest logs
    'claude_code': {'path': None, 'model': 'opus', 'effort': 'low'},
    'codex': {'path': None, 'model': None, 'effort': 'low'},
    # Vertex AI: Claude Code with its Vertex provider (vertex-claude-code) and the direct REST client (vertex)
    'vertex': {'project': None, 'region': 'global', 'model': 'claude-opus-5-5', 'effort': 'low',
               'fallback_model': 'claude-opus-4-8', 'gcloud': None},
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
    for key in ('enabled', 'allow_screenshot', 'observe_current_scene', 'prefetch_state'):
        if not isinstance(config[key], bool):
            raise ValueError(f'{path}: {key} must be true or false')
    if not isinstance(config['backends'], list) or any(name not in BACKENDS for name in config['backends']):
        raise ValueError(f'{path}: backends must be a list from {BACKENDS}')
    timeout = config['timeout_seconds']
    if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not 1 <= timeout <= 600:
        raise ValueError(f'{path}: timeout_seconds must be between 1 and 600')
    for key in ('claude_code', 'codex', 'vertex'):
        if not isinstance(config[key], dict):
            raise ValueError(f'{path}: {key} must be an object')
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

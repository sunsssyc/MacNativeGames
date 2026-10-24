"""技能: playbooks every channel can follow, in the format of Claude's Agent Skills: a folder per skill with a SKILL.md
whose front matter gives its name and when to use it, and whose body says how.

    ---
    name: shrine-puzzle
    description: 神庙或机关“怎么过”的问题：先查攻略、核对来源、按档位转述
    ---
    1. ...

The prompt lists every skill's name and description; the model reads one in full with the skill tool when a question
calls for it. Built-in skills ship with the assistant (totk_hint/skills/); the player's own go in the game's data folder
(skills/<name>/SKILL.md) and win over a built-in one of the same name."""
import re
from pathlib import Path

from .romfs import DATA_DIR

BUILT_IN = Path(__file__).resolve().parent / 'skills'
USER = DATA_DIR / 'skills'
MAX_CHARS = 6000
NAME = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')


def _parse(path):
    """(name, description, body) of a SKILL.md, or None when it is not one."""
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None
    m = re.match(r'(?s)\A---\s*\n(.*?)\n---\s*\n?(.*)\Z', text)
    if not m:
        return None
    fields = dict(re.findall(r'(?m)^(name|description):\s*(.+?)\s*$', m.group(1)))
    name, description = fields.get('name', '').strip('"\''), fields.get('description', '').strip('"\'')
    if not NAME.match(name) or not description:
        return None
    return name, description, m.group(2).strip()


def catalog(folders=None):
    """{name: {"description", "body", "source"}}: the built-in skills, then the player's own over them."""
    found = {}
    for folder, source in folders or ((BUILT_IN, 'built-in'), (USER, 'player')):
        for path in sorted(Path(folder).glob('*/SKILL.md')):
            parsed = _parse(path)
            if parsed:
                name, description, body = parsed
                found[name] = {'description': description, 'body': body[:MAX_CHARS], 'source': source}
    return found


def prompt_lines(skills):
    return [f'- {name}：{s["description"]}' for name, s in sorted(skills.items())]

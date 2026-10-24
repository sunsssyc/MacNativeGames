"""The frame the panel opened on, and the marks a model draws on it (指给我看).

The game (runtime/hint_overlay.m) saves hint-scene.png in its data folder just before it pauses behind the panel, so
while the panel is open the window still shows exactly that frame. A question sent with 指给我看 attaches it (as a
JPEG of at most 1280 pixels) and offers the mark_screen tool; the marks come back with the answer as fractions of the
picture, and the game draws them on the paused window."""
import json
import subprocess
from pathlib import Path

SCENE = 'hint-scene.png'
MAX_MARKS = 4
MAX_LABEL = 16


def size(path):
    """(width, height) of a picture (sips), or None."""
    done = subprocess.run(['/usr/bin/sips', '-g', 'pixelWidth', '-g', 'pixelHeight', str(path)], capture_output=True,
                          text=True)
    values = dict(line.split(':', 1) for line in done.stdout.splitlines()[1:] if ':' in line)
    try:
        return int(values['  pixelWidth'].strip()), int(values['  pixelHeight'].strip())
    except (KeyError, ValueError):
        return None


def prepare(folder):
    """(JPEG path, width, height) of the frame the panel opened on, or None when there is none."""
    png, jpg = Path(folder) / SCENE, Path(folder) / 'hint-scene.jpg'
    if not png.is_file():
        return None
    done = subprocess.run(['/usr/bin/sips', '-Z', '1280', '-s', 'format', 'jpeg', '-s', 'formatOptions', '80', str(png),
                           '--out', str(jpg)], capture_output=True)
    dimensions = size(jpg) if done.returncode == 0 else None
    return (jpg, *dimensions) if dimensions else None


TOOL = {
    'name': 'mark_screen',
    'description': 'Mark what the player should look at on the attached game picture (the frame the panel opened on; '
                   'the game is paused, so the window still shows it): 1-4 circles or arrows in that picture\'s '
                   'pixels, each with a short Chinese label. The game draws them over the paused window. A new call '
                   'replaces the marks. Mark only what you can actually see in the picture.',
    'inputSchema': {'type': 'object', 'properties': {'marks': {'type': 'array', 'minItems': 1, 'maxItems': MAX_MARKS, 'items': {
        'type': 'object', 'properties': {
            'kind': {'type': 'string', 'enum': ['circle', 'arrow'], 'description': 'circle around x,y; arrow from x,y to to_x,to_y'},
            'x': {'type': 'integer'}, 'y': {'type': 'integer'},
            'to_x': {'type': 'integer'}, 'to_y': {'type': 'integer'},
            'label': {'type': 'string', 'description': f'2-8 Chinese characters, at most {MAX_LABEL}'}},
        'required': ['kind', 'x', 'y', 'label'], 'additionalProperties': False}}},
        'required': ['marks'], 'additionalProperties': False},
}


def mark(arguments, width, height, out):
    """Check the marks against the picture and write them to out as fractions of it; the reply for the model."""
    marks = arguments.get('marks')
    if not isinstance(marks, list) or not 1 <= len(marks) <= MAX_MARKS:
        raise ValueError(f'marks: 1 to {MAX_MARKS} marks')

    def point(m, kx, ky):
        x, y = m.get(kx), m.get(ky)
        if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int) \
                or not (0 <= x <= width and 0 <= y <= height):
            raise ValueError(f'{kx},{ky} must be pixels inside the {width}x{height} picture')
        return [round(x / width, 4), round(y / height, 4)]
    kept = []
    for m in marks:
        if not isinstance(m, dict) or m.get('kind') not in ('circle', 'arrow'):
            raise ValueError('kind must be circle or arrow')
        label = m.get('label')
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > MAX_LABEL:
            raise ValueError(f'label: 1 to {MAX_LABEL} characters')
        entry = {'kind': m['kind'], 'at': point(m, 'x', 'y'), 'label': label.strip()}
        if m['kind'] == 'arrow':
            entry['to'] = point(m, 'to_x', 'to_y')
        kept.append(entry)
    Path(out).write_text(json.dumps({'marks': kept}, ensure_ascii=False), encoding='utf-8')
    return {'ok': True, 'marks': len(kept), 'note': '已标在暂停的游戏画面上；回答里可以说“圈出的…”'}


def read_marks(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8')).get('marks') or None
    except (OSError, ValueError, AttributeError):
        return None

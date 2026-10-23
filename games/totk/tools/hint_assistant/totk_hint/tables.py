"""Tables the harness needs, built once from the game's own data and cached under ~/Library/Caches (never in the repository):

- enum value names of the save flags (GameData/GameDataList.Product.*.byml.zs: each Enum flag lists its values and their
  murmur3 hashes; the save stores the hash),
- every quest ("challenge", RSDB/Challenge.Product.*.rstbl.byml.zs): category, steps in order and each step's map
  destinations; its progress is the Enum flag Step_<name> (NotReady, Ready, <steps...>, Complete),
- the quest log texts (Mals/<lang>.Product.*.sarc.zs, ChallengeMsg/Info_<name>.msbt: Name and one text per step),
- the map's named places with positions (Banc/<field>/LocationArea/*.locationarea.byml.zs) and their names
  (LocationMsg/Location.msbt), item names (ActorMsg/PouchContent.msbt),
- all of the game's text for search_text (a separate, larger file)."""
import json
import os
import uuid
import re
import time
from pathlib import Path

from .formats import Byml, msbt, sarc_members
from .romfs import find_romfs

FORMAT = 2
CACHE_ROOT = Path.home() / 'Library/Caches/MacNativeGames/TOTK/hint-assistant'
# quest categories as the adventure log groups them
CATEGORY_NAMES = {'Main': '主要任务', 'ImportantMini': '支线冒险', 'Sub': '神庙挑战', None: '支线任务'}


def _stem(path):
    return Path(path).name.split('.')[0]


def _one(romfs, pattern):
    found = romfs.find(pattern)
    if not found:
        raise FileNotFoundError(f'{romfs.folder}: no {pattern}')
    return found[-1]   # newest product version, e.g. GameDataList.Product.140 over .100


def _key(path):
    """'Work/Location/Dungeon045.game__location__Location.gyml' -> 'Dungeon045'."""
    return _stem(path) if path else None


def _enum_values(romfs):
    doc = Byml(romfs.read_zs(_one(romfs, 'GameData/GameDataList.Product.*.byml.zs')))
    data = next(raw for key, kind, raw in doc.items(doc.root_offset) if key == 'Data')
    values = {}
    for key, kind, raw in doc.items(data):
        if key not in ('Enum', 'EnumArray'):
            continue
        for k, v in doc.elements(raw):
            entry = doc.value(k, v)
            for name, h in zip(entry.get('RawValues') or (), entry.get('Values') or ()):
                values[str(h)] = name
    return values


def _challenges(romfs):
    rows = Byml(romfs.read_zs(_one(romfs, 'RSDB/Challenge.Product.*.rstbl.byml.zs'))).root()
    out = []
    for row in rows:
        steps = []
        for step in row.get('Steps') or ():
            dest = []
            for d in step.get('DestinationPoint') or ():
                pos = d.get('Pos') or d.get('AlternativePos')
                if pos:
                    dest.append({'pos': [round(pos['X'], 1), round(pos['Y'], 1), round(pos['Z'], 1)],
                                 'hide': d.get('BlackOutFlag') or '', 'actor': _key(d.get('Actor'))})
            steps.append({'name': step.get('Name'), 'nolog': bool(step.get('IsNotChangeAdventureLog')),
                          'minigame': bool(step.get('IsMiniGame')), 'dest': dest})
        out.append({'name': _key(row['__RowId']), 'category': row.get('Category'), 'sort': row.get('SortIndex', 99999),
                    'giver': _key(row.get('RequestActor')), 'place': _key(row.get('RequestLocation')), 'steps': steps})
    return out


def _locations(romfs):
    out = []
    for path in romfs.find('Banc/*/LocationArea/*.locationarea.byml.zs'):
        field = path.split('/')[1]
        for category, entries in Byml(romfs.read_zs(path)).root().items():
            for e in entries or ():
                key = _key(e.get('LocationName'))
                if key and e.get('Trans'):
                    out.append({'key': key, 'category': category, 'field': field,
                                'pos': [[round(v, 1) for v in t] for t in e['Trans']]})
    return out


def _messages(romfs, language):
    archive = romfs.read_zs(_one(romfs, f'Mals/{language}.Product.*.sarc.zs'))
    for name, (lo, hi) in sorted(sarc_members(archive).items()):
        if name.endswith('.msbt'):
            yield name, msbt(archive[lo:hi])


def build(romfs, language='CNzh'):
    t0 = time.monotonic()
    tables = {'format': FORMAT, 'language': language, 'romfs': str(romfs.folder), 'identity': romfs.identity()}
    tables['enums'] = _enum_values(romfs)
    tables['challenges'] = _challenges(romfs)
    tables['locations'] = _locations(romfs)
    quest_files = {f"ChallengeMsg/Info_{c['name']}.msbt": c['name'] for c in tables['challenges']}
    quest_text, names, items, corpus = {}, {}, {}, []
    for name, texts in _messages(romfs, language):
        if name in quest_files:
            quest_text[quest_files[name]] = texts
        elif name == 'LocationMsg/Location.msbt':
            names = texts
        elif name == 'ActorMsg/PouchContent.msbt':
            items = {label[:-5]: text for label, text in texts.items() if label.endswith('_Name') and text}
        if name.startswith('StaffRollMsg/'):
            continue
        for label, text in texts.items():
            if text.strip():
                corpus.append([name, label, text])
    tables.update(quest_text=quest_text, names=names, items=items)
    tables['seconds'] = round(time.monotonic() - t0, 2)
    return tables, corpus


def corpus_name(language):
    return f'corpus-{FORMAT}-{language}.json'


def cache_dir(romfs):
    return CACHE_ROOT / re.sub(r'[^A-Za-z0-9._-]', '_', f'{romfs.identity()}')


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')))
    tmp.replace(path)


class Tables:
    def __init__(self, data, folder):
        self.data = data
        self.folder = folder
        self.enums = {int(k): v for k, v in data['enums'].items()}
        self.challenges = data['challenges']
        self.by_name = {c['name']: c for c in self.challenges}
        self.locations = data['locations']
        self.names = data['names']
        self.items = data['items']
        self.quest_texts = data['quest_text']
        self._corpus = None

    def place_name(self, key):
        return self.names.get(key) or None

    def item_name(self, actor):
        return self.items.get(actor) or None

    def quest_name(self, name):
        return (self.quest_texts.get(name) or {}).get('Name') or None

    def corpus(self):
        if self._corpus is None:
            self._corpus = json.loads((self.folder / corpus_name(self.data['language'])).read_text())
        return self._corpus


def load(romfs_folder=None, config=None, rebuild=False, language=None):
    """The cached tables for the current game data, built on first use (a few seconds)."""
    language = language or (config or {}).get('text_language') or 'CNzh'
    try:
        romfs = find_romfs(romfs_folder, config)
    except FileNotFoundError:
        if rebuild:
            raise
        # no game data reachable (the app moved, an external disk is gone): the newest cache still answers
        cached = sorted(CACHE_ROOT.glob(f'*/tables-{FORMAT}-{language}.json'), key=lambda p: p.stat().st_mtime)
        if not cached:
            raise
        return Tables(json.loads(cached[-1].read_text()), cached[-1].parent)
    folder = cache_dir(romfs)
    path = folder / f'tables-{FORMAT}-{language}.json'
    if not rebuild and path.is_file() and (folder / corpus_name(language)).is_file():
        data = json.loads(path.read_text())
        if data.get('format') == FORMAT:
            return Tables(data, folder)
    data, corpus = build(romfs, language)
    _write_json(folder / corpus_name(language), corpus)
    _write_json(path, data)
    return Tables(data, folder)

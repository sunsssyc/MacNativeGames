"""The harness tools: what a model can ask about the player's game, answered from the save and the game's own data so a
hint is grounded instead of guessed. Shared by the MCP server (Claude Code, Codex) and the Vertex AI tool loop.

    game_state   where Link is, health and abilities, story progress and collection counts (newest save)
    quest_log    active quests with the adventure log's text for the current step and where its map targets are
    search_text  the game's Simplified Chinese text (quests, places, items, tips, dialogue)
    screenshot   the game window, only while the game runs and only when the player allowed it

Everything is read-only. The only thing ever written outside the cache is the "wshot <png>" line the game's command
channel understands (runtime/input.c), and only for screenshot."""
import base64
import json
import math
import os
import subprocess
import time
from pathlib import Path

from . import save as savemod
from . import tables as tablemod
from .romfs import DATA_DIR

COMPASS = ('北', '东北', '东', '东南', '南', '西南', '西', '西北')
# map marker categories worth naming as "near ..." (shops, region labels and unnamed markers are left out)
# how strongly a kind of place is preferred when naming where a quest target is (smaller: preferred at a larger distance)
LANDMARK_WEIGHT = {'城镇': 0.45, '驿站': 0.6, '鸟望台': 0.6, '神殿': 0.6, '空岛群': 0.8, '地点': 1.0, '神庙': 1.1, '光之根': 1.1,
                   '洞窟': 1.3, '深穴': 1.3, '井': 1.3}
PLACE_KINDS = {'City': '城镇', 'Stable': '驿站', 'Tower': '鸟望台', 'Shrine': '神庙', 'CheckPoint': '光之根',
               'Dungeon': '神殿', 'SkyArchipelago': '空岛群', 'CaveEntranceNormal': '洞窟', 'CaveEntranceSpecial': '深穴',
               'CaveEntranceWell': '井', 'Ground': '地点', 'Underground': '地点'}
LAYERS = {'ground': '地表', 'sky': '空岛', 'depths': '地底'}
ABILITIES = ('Obj_UltraHand', 'Obj_OneTouchBond', 'Obj_Tooreroof', 'Obj_ReverseRecorder', 'Obj_AutoBuilder',
             'Obj_Camera', 'Parasail', 'Obj_SheikSensor', 'Obj_SheikSensorLv2', 'Obj_Battery_Get')
SAGES = ('Obj_SageSoul_Rito', 'Obj_SageSoul_Gerudo', 'Obj_SageSoul_Goron', 'Obj_SageSoul_Zora', 'Obj_SageSoul_Zonau')
SEARCH_SOURCES = (('ChallengeMsg/', '任务日志'), ('LocationMsg/', '地名'), ('ActorMsg/PouchContent', '物品'),
                  ('StaticMsg/Tips', '提示'), ('ActorMsg/', '角色与物品'), ('StaticMsg/', '游戏说明'), ('LayoutMsg/', '界面'),
                  ('EventFlowMsg/', '对话与事件'), ('NpcTerrorMsg/', '对话与事件'), ('ShoutMsg/', '对话与事件'))
SHOTS = tablemod.CACHE_ROOT / 'shots'


class ToolError(Exception):
    """A tool could not answer; the message goes back to the model as the tool's result."""


def _round(v):
    return [round(x, 1) for x in v]


def relation(src, dst):
    """Direction (8 points of the compass; north is -z on the map), horizontal distance and height of dst from src."""
    dx, dn = dst[0] - src[0], src[2] - dst[2]
    dist = math.hypot(dx, dn)
    up = dst[1] - src[1]
    if dist < 15:
        text = '就在附近'
    else:
        heading = COMPASS[int(((math.degrees(math.atan2(dx, dn)) + 360) % 360 + 22.5) // 45) % 8]
        text = f'{heading}方 约 {round(dist, -1):.0f} 米' if dist < 1000 else f'{heading}方 约 {dist / 1000:.1f} 公里'
    if abs(up) >= 40:
        text += f'，{"高" if up > 0 else "低"}约 {abs(round(up, -1)):.0f} 米'
    return {'text': text, 'distance_m': round(dist), 'height_m': round(up)}


def field_of(pos):
    return 'MinusField' if pos[1] < -100 else 'MainField'


class Places:
    """Named map markers by field, for "near X" descriptions and the rough region."""

    def __init__(self, tables):
        self.by_field = {}
        self.regions = []
        for loc in tables.locations:
            name = tables.place_name(loc['key'])
            if not name:
                continue
            if loc['category'] == 'District':
                self.regions.append((name, loc['key'], loc['pos'][0]))
            elif loc['category'] in PLACE_KINDS or loc['category'].startswith('Spot'):
                kind = PLACE_KINDS.get(loc['category'], '地点')
                self.by_field.setdefault(loc['field'], []).append((name, kind, loc['key'], loc['pos']))

    def near(self, pos, field=None, limit=3, radius=2500.0, landmarks=False):
        """Named places around pos, nearest first; landmarks=True prefers towns, stables and towers over a shrine or a
        cave that happens to be a little closer (for saying where a quest target is)."""
        out, seen = [], set()
        for name, kind, key, positions in self.by_field.get(field or field_of(pos), ()):
            d = min(math.dist(pos, p) for p in positions)
            if d <= radius:
                score = d * LANDMARK_WEIGHT.get(kind, 1.0) if landmarks else d
                out.append((score, name, kind, key, min(positions, key=lambda p: math.dist(pos, p))))
        out.sort()
        result = []
        for _, name, kind, key, p in out:
            if name in seen:
                continue
            seen.add(name)
            result.append({'name': name, 'kind': kind, 'id': key, 'from_link': relation(pos, p)['text']})
            if len(result) == limit:
                break
        return result

    def region(self, pos, layer):
        """The map region whose label is nearest (horizontally): a rough guide, not the game's exact border."""
        sky = layer == 'sky'
        candidates = [(math.hypot(pos[0] - p[0], pos[2] - p[2]), name) for name, key, p in self.regions
                      if key.endswith('_Sky') == sky]
        return min(candidates)[1] if candidates else None


def _quarter(v):
    return None if v is None else (v // 4 if v % 4 == 0 else v / 4)


class Harness:
    def __init__(self, config=None, romfs=None, save_root=None, allow_screenshot=False):
        self.config = config or {}
        self.romfs = romfs
        self.roots = savemod.save_roots(save_root, self.config)
        self.allow_screenshot = allow_screenshot
        self._tables = None
        self._places = None

    # data -------------------------------------------------------------------------------------------------------------
    @property
    def tables(self):
        if self._tables is None:
            self._tables = tablemod.load(self.romfs, self.config)
        return self._tables

    @property
    def places(self):
        if self._places is None:
            self._places = Places(self.tables)
        return self._places

    def slot(self, name=None):
        if name:
            for s in savemod.slots(self.roots):
                if s.folder.name == name:
                    return s
            raise ToolError(f'没有名为 {name} 的存档槽')
        try:
            return savemod.newest(self.roots)
        except FileNotFoundError as e:
            raise ToolError(f'找不到存档：{e}') from None

    def quest_states(self, data):
        enums = self.tables.enums
        return {c['name']: data.enum('Step_' + c['name'], enums) for c in self.tables.challenges}

    def _where(self, data, caption):
        """(world position, layer key, inside {id, name} or None) of Link in this save."""
        banc = data.string('Sequence_CurrentBanc') or 'MainField'
        pos = data.vec3('PlayerStatus.SavePos') or data.vec3('World_PlayerPos')
        inside = None
        if banc != 'MainField':
            inside = {'id': banc, 'name': self.tables.place_name(banc) or banc}
            if caption and caption.position:   # inside a shrine progress.sav holds the shrine's own coordinates
                pos = caption.position
        layer = caption.layer if caption else None
        if layer is None and pos:
            layer = 'depths' if pos[1] < -100 else 'sky' if pos[1] > 1200 else 'ground'
        return pos, layer, inside

    # tools ------------------------------------------------------------------------------------------------------------
    def game_state(self, slot=None):
        s = self.slot(slot)
        data, caption, t = s.load(), s.caption, self.tables
        pos, layer, inside = self._where(data, caption)
        states = self.quest_states(data)
        location = {'layer': LAYERS.get(layer, layer)}
        if inside:
            kind = '神庙' if inside['id'].startswith('Dungeon') else '神殿' if inside['id'].startswith('LargeDungeon') else '室内'
            location['inside'] = f"{inside['name']}（{kind}内部）"
        if caption and caption.place:
            location['save_place'] = t.place_name(caption.place) or caption.place
        if pos:
            location['region'] = self.places.region(pos, layer)
            location['nearby'] = self.places.near(pos, 'MinusField' if layer == 'depths' else 'MainField')
            location['xyz'] = _round(pos)
            location['axes'] = 'x 向东增大，z 向南增大（北为 -z），y 为高度，单位米'
        player = {'hearts': _quarter(data.int('PlayerStatus.MaxLife')), 'hearts_now': _quarter(data.int('PlayerStatus.Life')),
                  'stamina_wheels': None, 'battery_cells': None, 'rupees': data.int('PlayerStatus.CurrentRupee')}
        stamina, energy = data.float('PlayerStatus.MaxStamina'), data.float('PlayerStatus.MaxEnergy')
        if stamina is not None:
            player['stamina_wheels'] = round(stamina / 1000, 2)
        if energy is not None:
            player['battery_cells'] = round(energy / 1000, 1)   # 1000 per cell; a new game has 3000
        abilities = [t.item_name(a) or a for a in ABILITIES if data.bool('IsGet.' + a)]
        sages = [t.item_name(a) or a for a in SAGES if data.bool('IsGet.' + a)]
        main_active, main_done, main_open = [], [], 0
        for c in sorted(t.challenges, key=lambda c: c['sort']):
            if c['category'] != 'Main':
                continue
            state, name = states.get(c['name']), t.quest_name(c['name']) or c['name']
            if state == 'Complete':
                main_done.append(name)
            elif state and state not in ('NotReady', 'Ready'):
                main_active.append(f'{name}（{state}）')
            else:
                main_open += 1
        shrines = [l['key'] for l in t.locations if l['category'] == 'Shrine' and l['field'] == 'MainField']
        shrine_states = [data.enum('DungeonState.' + k, t.enums) for k in shrines]
        lightroots = [l['key'] for l in t.locations if l['category'] == 'CheckPoint']
        towers = [l['key'] for l in t.locations if l['category'] == 'Tower']
        tears = [l['key'] for l in t.locations if l['category'] == 'DragonTears']
        stock = dict(zip(data.strings('Pouch.KeyItem.Content.Name') or (), data.ints('Pouch.KeyItem.Content.StockNum') or ()))
        progress = {
            'sages_awakened': data.int('NumOfSageClear'),
            'main_quests_in_progress': main_active, 'main_quests_done': main_done, 'main_quests_not_started': main_open,
            'shrines': {'cleared': shrine_states.count('Clear'),
                        'visited': sum(1 for k in shrines if data.bool('IsVisitLocation.' + k)), 'total': len(shrines)},
            'lightroots_visited': {'count': sum(1 for k in lightroots if data.bool('IsVisitLocation.' + k)), 'total': len(lightroots)},
            'skyview_towers_activated': {'count': sum(1 for k in towers if data.bool('IsOpenCannon.' + k)), 'total': len(towers)},
            'dragon_tears_memories': {'count': sum(1 for k in tears if data.bool('Complete_' + k)), 'total': len(tears)},
            'korok_seeds_in_pouch': max(stock.get('Obj_KorokNuts', 0), 0),
            'lights_of_blessing_in_pouch': max(stock.get('Obj_DungeonClearSeal', 0), 0),
        }

        def names(category, counts=False):
            items = [n for n in data.strings(f'Pouch.{category}.Content.Name') or () if n]
            nums = data.ints(f'Pouch.{category}.Content.StockNum') or []
            out = []
            for i, actor in enumerate(items):
                label = t.item_name(actor) or actor
                if counts and i < len(nums) and nums[i] > 1:
                    label += f'×{nums[i]}'
                if label not in out:
                    out.append(label)
            return out
        inventory = {'armor': names('Armor'), 'weapons': names('Weapon'), 'bows': names('Bow'), 'shields': names('Shield'),
                     'key_items': names('KeyItem', counts=True), 'zonai_devices': names('SpecialParts', counts=True),
                     'materials_kinds': len(names('Material')), 'meals': len(names('Food'))}
        info = {'slot': s.folder.name, 'game_version': data.version}
        if caption and caption.saved_at:
            info['saved_at'] = caption.saved_at.isoformat(sep=' ')
        info['file_time'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(s.mtime))
        return {'save': info, 'location': location, 'player': player, 'abilities': abilities, 'sage_vows': sages,
                'progress': progress, 'inventory': inventory}

    def _hidden(self, flag, data, states):
        """Whether a quest target's hide flag is set: True, False, or None when it cannot be read from the save."""
        if not flag:
            return False
        if flag.endswith('_IsCompleted_Exp') and flag[:-16] in states:
            return states[flag[:-16]] == 'Complete'
        if flag.endswith('_Exp') and '_IsAfter_' in flag:
            name, step = flag[:-4].split('_IsAfter_', 1)
            if name in states and name in self.tables.by_name:
                order = [s['name'] for s in self.tables.by_name[name]['steps']]
                state = states[name]
                if state == 'Complete':
                    return True
                if state in order and step in order:
                    return order.index(state) > order.index(step)
        return data.bool(flag)

    def _log_text(self, quest, state):
        texts = self.tables.quest_texts.get(quest['name'], {})
        if state == 'Complete':
            return texts.get('Complete')
        names = [s['name'] for s in quest['steps']]
        if state not in names:
            return None
        for step in reversed(quest['steps'][:names.index(state) + 1]):
            if not step['nolog'] and texts.get(step['name']):
                return texts[step['name']]
        return None

    def quest_log(self, query=None, include_completed=False, limit=12, slot=None):
        s = self.slot(slot)
        data, caption, t = s.load(), s.caption, self.tables
        pos, layer, inside = self._where(data, caption)
        states = self.quest_states(data)
        active, done = [], []
        for quest in t.challenges:
            state = states.get(quest['name'])
            if not state or state in ('NotReady', 'Ready'):
                continue
            name = t.quest_name(quest['name']) or quest['name']
            if state == 'Complete':
                done.append((quest, name))
                continue
            log = self._log_text(quest, state)
            entry = {'quest': name, 'id': quest['name'], 'type': tablemod.CATEGORY_NAMES.get(quest['category'], '支线任务'),
                     'step': state, 'log': log}
            if quest['place']:
                entry['given_at'] = t.place_name(quest['place']) or quest['place']
            step = next((st for st in quest['steps'] if st['name'] == state), None)
            targets, best = [], math.inf
            for d in (step or {}).get('dest', ()):
                hidden = self._hidden(d['hide'], data, states)
                if hidden:
                    continue
                target = {'xyz': d['pos']}
                near = self.places.near(d['pos'], field_of(d['pos']), limit=1, radius=4000, landmarks=True)
                if near:
                    target['near'] = f"{near[0]['name']}（{near[0]['kind']}）"
                if pos and not inside:
                    rel = relation(pos, d['pos'])
                    target['from_link'] = rel['text']
                    best = min(best, rel['distance_m'])
                if hidden is None:
                    target['note'] = '这个目标是否已完成无法从存档判断'
                targets.append(target)
            if targets:
                entry['targets'] = targets[:4]
            entry['_rank'] = (0 if quest['category'] == 'Main' else 1, best, quest['sort'])
            active.append(entry)
        if query:
            q = query.lower()
            active = [e for e in active if q in json.dumps(e, ensure_ascii=False).lower()]
            done = [(c, n) for c, n in done if q in n.lower() or q in c['name'].lower()]
        active.sort(key=lambda e: e.pop('_rank'))
        out = {'save_slot': s.folder.name, 'active_total': len(active), 'active': active[:max(1, min(int(limit or 12), 40))]}
        if pos and not inside:
            out['link_xyz'] = _round(pos)
        out['note'] = '主要任务在前，其余按目标离林克由近到远排列；log 是游戏冒险日志里这一步的原文，【】是游戏高亮的词'
        main_done = [n for c, n in done if c['category'] == 'Main']
        out['main_quests_done'] = main_done
        if include_completed or query:
            out['other_quests_done'] = [n for c, n in done if c['category'] != 'Main']
        else:
            out['other_quests_done_count'] = len(done) - len(main_done)
        return out

    def search_text(self, query, limit=10):
        terms = [w.lower() for w in str(query or '').split() if w]
        if not terms:
            raise ToolError('query 为空')
        limit = max(1, min(int(limit or 10), 30))
        quest_names = {f"ChallengeMsg/Info_{c['name']}.msbt": c['name'] for c in self.tables.challenges}
        try:
            states = self.quest_states(self.slot().load())
        except (ToolError, OSError, ValueError):
            states = {}
        hits = []
        for file, label, text in self.tables.corpus():
            hay = f'{text}\n{label}\n{file}'.lower()
            if all(term in hay for term in terms):
                rank = next((i for i, (prefix, _) in enumerate(SEARCH_SOURCES) if file.startswith(prefix)), len(SEARCH_SOURCES))
                hits.append((rank, len(text), file, label, text))
        hits.sort()
        results = []
        for rank, _, file, label, text in hits[:limit]:
            item = {'source': SEARCH_SOURCES[rank][1] if rank < len(SEARCH_SOURCES) else '其他', 'file': file, 'label': label,
                    'text': text if len(text) <= 260 else text[:260] + '…'}
            if file in quest_names:
                name = quest_names[file]
                item['quest'] = self.tables.quest_name(name)
                item['quest_id'] = name
                item['player_progress'] = self._progress_of(name, label, states.get(name))
            results.append(item)
        return {'query': query, 'total': len(hits), 'results': results,
                'note': 'player_progress 说明玩家是否已经走到这条任务日志；"尚未到达" 的内容和对话类文字可能剧透，只在提示等级允许时使用'}

    def _progress_of(self, quest, label, state):
        """Whether the player's save has reached the quest log line `label` of `quest`."""
        if label == 'Name':
            return '任务名'
        if not state or state in ('NotReady', 'Ready'):
            return '任务尚未开始'
        if state == 'Complete':
            return '已完成的任务'
        order = [s['name'] for s in self.tables.by_name[quest]['steps']]
        if label == 'Complete':
            return '尚未到达'
        if label in order and state in order:
            return '已经历' if order.index(label) < order.index(state) else '当前步骤' if label == state else '尚未到达'
        return '未知'

    # screenshot -------------------------------------------------------------------------------------------------------
    @staticmethod
    def game_pid():
        """The running game's pid (runtime/game_slot.c names it in game-slot/holder), else any build/totk-native process."""
        try:
            values = dict(line.split('=', 1) for line in (DATA_DIR / 'game-slot/holder').read_text().splitlines() if '=' in line)
            pid = int(values.get('game_pid') or 0)
            if pid > 0:
                command = subprocess.run(['ps', '-o', 'command=', '-p', str(pid)], capture_output=True, text=True).stdout
                if 'totk-native' in command:
                    return pid
        except (OSError, ValueError):
            pass
        found = subprocess.run(['pgrep', '-f', 'build/totk-native'], capture_output=True, text=True).stdout.split()
        return int(found[0]) if found else None

    def screenshot(self, timeout=8.0):
        if not self.allow_screenshot:
            raise ToolError('玩家没有允许这次提示截图（assistant.json 的 allow_screenshot，或请求里的 screenshot）')
        if not self.game_pid():
            raise ToolError('游戏没有在运行，无法截图')
        SHOTS.mkdir(parents=True, exist_ok=True)
        png = SHOTS / f'hint-{int(time.time() * 1000)}.png'
        if any(c in str(png) for c in '\r\n\0'):
            raise ToolError('截图路径不可用')
        commands = Path(os.environ.get('TOTK_INPUT_FILE') or DATA_DIR / 'input.txt')
        # The game's command channel (runtime/input.c): one complete line, appended in a single write.
        fd = os.open(commands, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, f'wshot {png}\n'.encode())
        finally:
            os.close(fd)
        deadline, last = time.monotonic() + timeout, -1
        while time.monotonic() < deadline:
            time.sleep(0.25)
            try:
                size = png.stat().st_size
            except OSError:
                continue
            if size == last and size > 0 and png.read_bytes()[-8:-4] == b'IEND':
                break
            last = size
        else:
            raise ToolError('游戏没有写出截图（窗口被遮挡或游戏正在加载时可能取不到画面）')
        jpeg = png.with_suffix('.jpg')
        made = subprocess.run(['/usr/bin/sips', '-Z', '1280', '-s', 'format', 'jpeg', '-s', 'formatOptions', '80',
                               str(png), '--out', str(jpeg)], capture_output=True)
        image = jpeg if made.returncode == 0 and jpeg.is_file() else png
        for old in sorted(SHOTS.glob('hint-*'), key=lambda p: p.stat().st_mtime)[:-8]:   # keep the last few
            old.unlink(missing_ok=True)
        return {'path': str(image), 'note': '当前游戏画面（含窗口上的提示框）'}, image

    # dispatch ---------------------------------------------------------------------------------------------------------
    def tool_specs(self):
        specs = [
            {'name': 'game_state',
             'description': "Tears of the Kingdom: the player's current save (newest slot) read from disk. Where Link is "
                            "(layer: 地表/空岛/地底, inside a shrine, the save list's place name, rough region, nearest named "
                            "places with direction and distance), hearts/stamina/battery/rupees, unlocked abilities, sage "
                            "vows, main story progress, shrine/lightroot/tower/dragon-tear counts, armor, weapons, key items "
                            "and Zonai devices. Names are the game's own Simplified Chinese.",
             'inputSchema': {'type': 'object', 'properties': {
                 'slot': {'type': 'string', 'description': 'slot_00 ... slot_05; default: the save being played'}},
                 'additionalProperties': False}},
            {'name': 'quest_log',
             'description': "Active quests in the save, main quests first, with the game's adventure-log text (Simplified "
                            "Chinese; 【】 marks the words the game highlights) for the current step, and that step's map "
                            "targets: nearest named place plus direction/distance from Link (north is up on the map). "
                            "Optional query filters by quest name, id or text.",
             'inputSchema': {'type': 'object', 'properties': {
                 'query': {'type': 'string', 'description': 'words in the quest name or log, or a quest id'},
                 'include_completed': {'type': 'boolean', 'description': 'also list finished side quests'},
                 'limit': {'type': 'integer', 'description': 'at most this many active quests (default 12)'}},
                 'additionalProperties': False}},
            {'name': 'search_text',
             'description': "Search all of the game's Simplified Chinese text (quest logs, place names, items, tips, "
                            "dialogue) for every given word; returns matching lines with where they come from. Use it to "
                            "check names and facts instead of guessing. Dialogue lines can spoil later events.",
             'inputSchema': {'type': 'object', 'properties': {
                 'query': {'type': 'string', 'description': 'one or more words separated by spaces, e.g. 希多 水架桥'},
                 'limit': {'type': 'integer', 'description': 'at most this many lines (default 10, max 30)'}},
                 'required': ['query'], 'additionalProperties': False}},
        ]
        if self.allow_screenshot:
            specs.append({'name': 'screenshot',
                          'description': 'Capture the game window now (the player allowed it for this hint). Returns the '
                                         'picture; use it when the save alone cannot tell what the player is looking at.',
                          'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}})
        return specs

    def call(self, name, arguments=None):
        """Run a tool: (JSON text, image path or None). Raises ToolError for answers the model should see as errors."""
        args = dict(arguments or {})
        if name == 'game_state':
            result, image = self.game_state(args.get('slot')), None
        elif name == 'quest_log':
            result, image = self.quest_log(args.get('query'), bool(args.get('include_completed')), args.get('limit') or 12,
                                           args.get('slot')), None
        elif name == 'search_text':
            result, image = self.search_text(args.get('query'), args.get('limit') or 10), None
        elif name == 'screenshot':
            result, image = self.screenshot()
        else:
            raise ToolError(f'unknown tool {name}')
        return json.dumps(result, ensure_ascii=False), image


def image_block(path):
    """(media type, base64) of a screenshot file."""
    data = Path(path).read_bytes()
    return ('image/jpeg' if str(path).endswith('.jpg') else 'image/png'), base64.b64encode(data).decode()


def compact_snapshot(harness):
    """The short state the hint prompt starts with (the model can still call the tools for more)."""
    state = harness.game_state()
    quests = harness.quest_log(limit=6)
    return {'game_state': state, 'quest_log': quests}


"""The harness tools: what a model can ask about the player's game, answered from the save and the game's own data so a
hint is grounded instead of guessed. Shared by the MCP server (Claude Code, Codex) and the Vertex AI tool loop.

    game_state   where Link is, health and abilities, story progress and collection counts (newest save)
    quest_log    active quests with the adventure log's text for the current step and where its map targets are
    search_text  the game's Simplified Chinese text (quests, places, items, tips, dialogue)
    guide        how a shrine or a quest is solved, from public guides found by the game's own English name (guides.py)
    memory       earlier questions and answers, and notes the model keeps about the player (memory.py)
    screenshot   the game window, only while the game runs and only when the player allowed it

Everything is read-only. The only thing ever written outside the cache is the "wshot <png>" line the game's command
channel understands (runtime/input.c), and only for screenshot; guide reads public web pages and caches them, and
memory writes the assistant's own memory file."""
import base64
import json
import math
import os
import re
import subprocess
import time
from pathlib import Path

from .live import BUTTONS
from . import guides as guidemod
from . import memory as memorymod
from . import save as savemod
from . import scene as scenemod
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
CURRENT = ('', 'current', 'here', '当前', '这里', '这个')
SHRINE_NEAR = 600   # m: the shrine "here" is, when Link stands in the world (an entrance is a few dozen metres across)


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


# runtime_state's actors (runtime/world_survey.c, read from the game's actor table): the game's internal names, made
# readable here. Attached equipment and the game's own machinery are left out; a prefix gives the kind, words in the
# name a rough Chinese gloss (a guess from the name, not the game's text).
LIVE_SYSTEM = re.compile(r'^(PlayerCamera|EventCamera|RECCamera|CameraXLinkControl|CombinedActorIntegrator|VoicePlayActor|'
                         r'EventWorldManagerController|EventEffectEmitter|PlayerRaulHand|MergedActorUncond|Dm_Locator|'
                         r'PostProcessingActor|EffectUI|ReactionHit|ReactionField|Chemical|SpecialPower|Area|UltraHand|'
                         r'NormalArrow|ThrowBox|CarryBox|Parasail|WakeBoardRope|Obj_OneTouch_Connection|'
                         r'FldObj_EnterAttetionActor|GameDataActor|\w*SystemActor|\w*TextNPC|Expand\w*Field\w*|PurificationWave\w*|'
                         r'PlayerShockWave|PlayerAttackGrave|ElectricWaterBall|Exterminator|MergedActor\w*|'
                         r'ForbidAutoPlacement\w*|SoulSage_\w*Arrow\w*)$')
LIVE_ATTACHED = ('Armor_', 'Weapon_', 'Accessory_', 'Item_')   # within 1.5 m: what Link wears or holds
LIVE_KINDS = (('Sage_Soul_', '贤者分身'), ('DgnObj_', '神庙机关'), ('TBox_', '宝箱'), ('SpObj_', '机关装置'), ('Npc_', '人物'), ('Enemy_', '敌人'),
              ('FldObj_', '场景物件'), ('Obj_', '物件'), ('Item_', '道具'), ('Weapon_', '武器'), ('Animal_', '动物'),
              ('Horse_', '马'), ('Dm_', '演出物件'))
LIVE_WORDS = (('TrolleyRail', '矿车轨道'), ('WindGenerator', '风扇'), ('Warpin', '入口传送台'), ('Wing', '翅膀'),
              ('Cart', '矿车'), ('Rail', '轨道'), ('Fan', '风扇'), ('Generator', '生成装置'), ('Battery', '电池'),
              ('Switch', '开关'), ('Lever', '拉杆'), ('Door', '门'), ('Gate', '门'), ('Ball', '球'), ('Rocket', '火箭'),
              ('Balloon', '热气球'), ('Wheel', '车轮'), ('Spring', '弹簧'), ('Elevator', '升降台'), ('Pillar', '柱子'),
              ('Floor', '地板'), ('Laser', '光线'), ('Beam', '光线'), ('Mirror', '镜子'), ('Goal', '终点'),
              ('Dungeon', '神庙'), ('Gerudo', '格鲁德族'), ('Rito', '利特族'), ('Zora', '佐拉族'), ('Goron', '鼓隆族'),
              ('Tree', '树'), ('Apple', '苹果'), ('BeeHome', '蜂巢'), ('Bee', '蜜蜂'), ('Stone', '石'), ('Iron', '铁'), ('Wood', '木'), ('Ice', '冰'), ('Fire', '火'),
              ('Water', '水'), ('Electric', '电'))
CONTROL = re.compile(r'〔[^〕]*〕')   # what formats.msbt leaves of a text's control codes ("旅人之剑〔按键〕")
SIDES = ('正前方', '右前方', '右侧', '右后方', '正后方', '左后方', '左侧', '左前方')


def heading_of(vector):
    """Degrees clockwise from north (north is -z) of a horizontal direction."""
    return math.degrees(math.atan2(vector[0], -vector[2])) % 360


def live_view(state):
    """runtime_state as the model reads it: facing in words, the actors nearby named and placed relative to Link, and
    a scene guess (title screen, inside a shrine) judged from them. The raw position, facing and camera stay."""
    if not isinstance(state, dict) or not state.get('position'):
        return state
    out = dict(state)
    pos, facing = state['position'], state.get('facing')
    facing_deg = heading_of(facing) if facing and math.hypot(facing[0], facing[2]) > 0.1 else None
    if facing_deg is not None:
        out['facing_text'] = f'面朝{COMPASS[int((facing_deg + 22.5) // 45) % 8]}'
    nearby, by_name = [], {}
    for actor in state.get('nearby') or []:
        name, where, d = actor.get('name') or '', actor.get('position'), actor.get('distance') or 0
        if not where or LIVE_SYSTEM.match(name) or (d < 1.5 and name.startswith(LIVE_ATTACHED)):
            continue
        if name in by_name and d - by_name[name]['distance_m'] < 30:   # a group of the same thing: one line, counted
            by_name[name]['count'] = by_name[name].get('count', 1) + 1
            continue
        entry = {'name': name, 'distance_m': round(d)}
        kind = next((zh for prefix, zh in LIVE_KINDS if name.startswith(prefix)), None)
        matched = []   # a word inside a longer one already matched (Rail in TrolleyRail) adds nothing
        for word, zh in LIVE_WORDS:
            if word in name and not any(word in m for m, _ in matched):
                matched.append((word, zh))
        gloss = [zh for _, zh in matched]
        if kind:
            entry['kind'] = kind
        if gloss:
            entry['gloss'] = ' '.join(dict.fromkeys(gloss))
        if facing_deg is not None and math.hypot(where[0] - pos[0], where[2] - pos[2]) >= 2:
            bearing = heading_of([where[0] - pos[0], 0, where[2] - pos[2]])
            entry['side'] = SIDES[int(((bearing - facing_deg) % 360 + 22.5) // 45) % 8]
        entry['where'] = relation(pos, where)['text']
        nearby.append(entry)
        by_name[name] = entry
    if 'nearby' in state:
        out['nearby'] = nearby[:20]
    if all(abs(v) < 1 for v in pos) and facing and abs(facing[2] - 1) < 0.01:
        out['scene_guess'] = '标题画面或加载中（林克停在原点）'
    elif any(a['name'].startswith(('DgnObj_', 'TBox_Dungeon')) for a in nearby):
        out['scene_guess'] = '在神庙里（附近有神庙机关）'
    if 'scene_guess' in out:
        out['scene_guess_note'] = '由林克位置和附近物体推断，不是游戏直接报告的场景'
    return out


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
    def __init__(self, config=None, romfs=None, save_root=None, allow_screenshot=False, allow_actions=False,
                 marks=None, scene_size=None, memory=None):
        self.config = config or {}
        # memory: the file (or a Memory) the memory tool reads and writes; off with assistant.json memory.enabled false
        on = (self.config.get('memory') or {}).get('enabled', True)
        self.memory = (memory if isinstance(memory, memorymod.Memory) else memorymod.Memory(memory)) if on else None
        self.romfs = romfs
        self.roots = savemod.save_roots(save_root, self.config)
        self.allow_screenshot = allow_screenshot
        self.allow_actions = allow_actions   # press_button / stop_action: the player allowed this request to act
        self.marks, self.scene_size = marks, scene_size   # mark_screen: where to write, on a picture this size (指给我看)
        self._tables = None
        self._tables_en = None
        self._places = None
        self._glossary = None

    # data -------------------------------------------------------------------------------------------------------------
    @property
    def tables(self):
        if self._tables is None:
            self._tables = tablemod.load(self.romfs, self.config)
        return self._tables

    @property
    def tables_en(self):
        """The game's English text (USen), for the names guides know a place or a quest by."""
        if self._tables_en is None:
            self._tables_en = tablemod.load(self.romfs, self.config, language='USen')
        return self._tables_en

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
        return {'source': 'disk_save_not_live', 'warning': '仅代表保存时刻，不能当作当前画面或实时血量位置', 'save': info, 'location': location, 'player': player, 'abilities': abilities, 'sage_vows': sages,
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

    # guides -----------------------------------------------------------------------------------------------------------
    def _live(self):
        """runtime_state as live_view gives it, or None when the game does not answer."""
        try:
            from .live import call
            state = call('state').get('state')
        except (ValueError, TimeoutError, OSError, AttributeError):
            return None
        return live_view(state) if isinstance(state, dict) and state.get('position') else None

    def _nearest_shrine(self, pos):
        """(id, distance in metres) of the shrine entrance nearest to a world position."""
        best = (math.inf, None)
        for loc in self.tables.locations:
            if loc['category'] == 'Shrine' and loc['field'] == 'MainField':
                best = min(best, (min(math.dist(pos, p) for p in loc['pos']), loc['key']))
        return best[1], best[0]

    def _named(self, text):
        """(id, kind) of the place or quest a name means: exact Chinese or English names first, then a part of one."""
        t, en = self.tables, self.tables_en
        if text in t.names:
            return text, 'place'
        if text in t.by_name:
            return text, 'quest'
        q = text.lower().replace(' ', '')
        candidates = []
        for kind, pairs in (('place', list(t.names.items()) + list(en.names.items())),
                            ('quest', [(c['name'], t.quest_name(c['name'])) for c in t.challenges] +
                                      [(c['name'], en.quest_name(c['name'])) for c in t.challenges])):
            for key, name in pairs:
                n = (name or '').lower().replace(' ', '')
                if n and (n == q or q in n):
                    candidates.append((n != q, not key.startswith('Dungeon'), len(n), key, kind))
        if not candidates:
            raise ToolError(f'游戏里没有叫“{text}”的神庙、地点或任务；先用 search_text 核对游戏里的原名')
        candidates.sort()
        exact = [c for c in candidates if not c[0]]
        keys = list(dict.fromkeys(c[3] for c in (exact or candidates)))
        if len(keys) > 1 and not exact:
            shown = '、'.join(t.place_name(k) or t.quest_name(k) or k for k in keys[:8])
            raise ToolError(f'“{text}”对得上好几个：{shown}；请用完整名字再查')
        return candidates[0][3], candidates[0][4]

    def whereabouts(self):
        """{id, name} of the shrine or interior the newest save is in, else None: what an answer is remembered as about."""
        try:
            s = self.slot()
            return self._where(s.load(), s.caption)[2]
        except (ToolError, OSError, ValueError):
            return None

    def memory_tool(self, action, text=None, about=None, note_id=None):
        if not self.memory:
            raise ToolError('记忆已关闭（assistant.json memory.enabled）')
        if action == 'recall':
            return self.memory.recall(text, about)
        if action == 'note':
            try:
                return {'saved': self.memory.note(text, about), 'text': text}
            except ValueError as e:
                raise ToolError(str(e)) from None
        if action == 'forget':
            return {'forgotten': self.memory.forget(str(note_id or ''))}
        raise ToolError('action 只能是 recall、note 或 forget')

    def _current(self):
        """(shrine id, how it was chosen) for "the one I am in": the live state first, the save as a fallback."""
        live = self._live()
        try:
            s = self.slot()
            _, _, inside = self._where(s.load(), s.caption)
        except (ToolError, OSError, ValueError):
            inside = None
        saved = inside['id'] if inside and inside['id'].startswith('Dungeon') else None
        guess = (live or {}).get('scene_guess') or ''
        if guess.startswith('标题'):
            raise ToolError('游戏在标题画面或加载中，还没进入存档，说不出是哪座神庙')
        if live and guess.startswith('在神庙里'):
            if saved:
                return saved, '林克此刻在神庙里（实时），存档记录进入的是这座'
            raise ToolError('林克此刻在神庙里，但存档没有记下是哪一座：请玩家说出神庙名字，再用名字查')
        if live:
            key, d = self._nearest_shrine(live['position'])
            if saved and d > SHRINE_NEAR:   # inside a shrine the position is the shrine's own: far from every entrance
                return saved, '存档记录在这座神庙里，实时位置附近没有神庙入口（多半还在里面）'
            if key and d <= SHRINE_NEAR:
                return key, f'离林克最近的神庙入口（实时位置，约 {round(d, -1):.0f} 米）'
            raise ToolError(f'林克附近 {SHRINE_NEAR} 米内没有神庙；问的若是任务或别的地方，请用名字查')
        if saved:
            return saved, '上次存档在这座神庙里（游戏没有在运行，无法实时核对）'
        raise ToolError('游戏没有在运行，存档也不在神庙里：请用神庙或任务的名字查')

    def glossary(self, text, limit=40):
        """{English name: the game's Chinese name} of the items, abilities, Zonai devices and places a guide's text
        mentions (Wing → 翼, Recall → 倒转乾坤): a retelling uses the game's names, not a translation of the guide's."""
        if self._glossary is None:
            t, en, pairs = self.tables, self.tables_en, {}
            for english, chinese in ((en.items, t.items), (en.names, t.names)):
                for key, name in english.items():
                    if name and len(name) >= 3 and chinese.get(key):
                        pairs.setdefault(CONTROL.sub('', name).strip(), CONTROL.sub('', chinese[key]).strip())
            names = sorted(pairs, key=len, reverse=True)   # Light of Blessing before Light
            pattern = re.compile(r'(?i)\b(' + '|'.join(re.escape(n) for n in names) + r')(?:e?s)?\b') if names else None
            self._glossary = (pattern, {n.lower(): (n, pairs[n]) for n in names})
        pattern, by_lower = self._glossary
        found = {}
        for m in pattern.finditer(text) if pattern else ():
            name, chinese = by_lower[m.group(1).lower()]
            found.setdefault(name, chinese)
            if len(found) == limit:
                break
        return found

    def actor_name(self, actor):
        """The game's Chinese name of an actor in the live state, when it has one: SpObj_LiftGeneratorWing_A_01 is the
        Zonai device 翼 (its capsule's name), weapons and materials are named as in the pouch."""
        items = self.tables.items
        name = items.get(actor)
        m = re.match(r'^(SpObj_\w+?)_([A-Z]_\d+)$', actor)
        if not name and m:
            name = items.get(f'{m.group(1)}_Capsule_{m.group(2)}') or items.get(f'{m.group(1)}_Capsule_A_01')
        return CONTROL.sub('', name).strip() or None if name else None

    def guide(self, target=None):
        text = str(target or '').strip()
        if text.lower() in CURRENT:
            key, how = self._current()
            kind = 'place'
        else:
            (key, kind), how = self._named(text), f'按名字“{text}”'
        t, en = self.tables, self.tables_en
        name = (t.place_name(key) if kind == 'place' else t.quest_name(key)) or key
        name_en = en.place_name(key) if kind == 'place' else en.quest_name(key)
        if not name_en:
            raise ToolError(f'{name} 没有英文名，找不到攻略页')
        label = '神庙' if key.startswith('Dungeon') else '任务' if kind == 'quest' else '地点'
        pages = guidemod.fetch(name_en, timeout=float((self.config.get('guides') or {}).get('timeout') or 8))
        out = {'target': {'id': key, 'name': name, 'name_en': name_en, 'kind': label, 'chosen_by': how},
               'sources': pages}
        if pages:
            out['names'] = self.glossary('\n'.join(p['text'] for p in pages))
        if pages:
            out['note'] = ('攻略原文是英文网站的完整解法：只按玩家要的档位转述；names 是攻略里出现的名称在游戏里的中文原名，'
                           '转述时一律用它（例如 Wing 说“翼”，不要自己翻译），其他名称拿不准用 search_text 核对；回答末尾注明'
                           '依据的网站名；几处来源不一致时以多数为准，说不准的步骤以“建议”开头')
        else:
            out['note'] = '这次没取到攻略（网络不通或网站没有这一页）：不要凭画面猜解法，可以请玩家描述眼前的机关'
        return out

    # screenshot -------------------------------------------------------------------------------------------------------
    @staticmethod
    def game_pid():
        """The running game's pid (runtime/game_slot.c names it in game-slot/holder), else a process named totk-native
        (by its executable: a command line that merely mentions build/totk-native is not the game)."""
        try:
            values = dict(line.split('=', 1) for line in (DATA_DIR / 'game-slot/holder').read_text().splitlines() if '=' in line)
            pid = int(values.get('game_pid') or 0)
            if pid > 0:
                command = subprocess.run(['ps', '-o', 'command=', '-p', str(pid)], capture_output=True, text=True).stdout
                if 'totk-native' in command:
                    return pid
        except (OSError, ValueError):
            pass
        found = subprocess.run(['pgrep', '-x', 'totk-native'], capture_output=True, text=True).stdout.split()
        return int(found[0]) if found else None

    def screenshot(self, timeout=8.0):
        if not self.allow_screenshot:
            raise ToolError('玩家没有允许这次提示截图（assistant.json 的 allow_screenshot，或请求里的 screenshot）')
        if not self.game_pid():
            raise ToolError('游戏没有在运行，无法截图')
        # Behind the open panel the game is paused and draws no new frame to capture: the frame the panel opened on is
        # what the window shows.
        try:
            from .live import call
            paused = call('state').get('state', {}).get('assistant_paused')
        except (ValueError, TimeoutError, OSError, AttributeError):
            paused = False
        prepared = scenemod.prepare(DATA_DIR) if paused else None
        if prepared:
            jpg, width, height = prepared
            return {'path': str(jpg), 'width': width, 'height': height,
                    'note': '面板打开时的画面（游戏在面板后暂停，窗口里就是这一帧）'}, jpg
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
        width, height = scenemod.size(image) or (None, None)
        return {'path': str(image), 'width': width, 'height': height, 'note': '当前游戏画面（含窗口上的提示框）'}, image

    # dispatch ---------------------------------------------------------------------------------------------------------
    def tool_specs(self):
        specs = [
            {'name': 'wait_state',
             'description': 'Wait up to 1000 ms, then read runtime state. Does not advance paused simulation.',
             'inputSchema': {'type': 'object', 'properties': {
                 'duration_ms': {'type': 'integer', 'minimum': 0, 'maximum': 1000}}, 'additionalProperties': False}},
            {'name': 'runtime_state',
             'description': 'Read the running game now: Link\'s position and facing, the camera, the objects within '
                            '150 m (the game\'s internal names with a kind and, where the game has one, its Chinese name '
                            '(name_zh), else a Chinese gloss guessed from the name, '
                            'where they are and on which side of Link), and a scene guess (title screen, in a shrine) '
                            'judged from them. Health and quests are not read live. Never substitute saved values.',
             'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
        ]
        if self.allow_actions:
            specs += [
                {'name': 'press_button',
                 'description': 'Perform ONE game input the player asked for, 30..1000 ms, then return live state. '
                                'Changes gameplay. The game allows only a few presses per request. Confirm the outcome '
                                'from state; acknowledgement does not prove game effect.',
                 'inputSchema': {'type': 'object', 'properties': {
                     'button': {'type': 'string', 'enum': list(BUTTONS)},
                     'duration_ms': {'type': 'integer', 'minimum': 30, 'maximum': 1000}},
                     'required': ['button'], 'additionalProperties': False}},
                {'name': 'stop_action', 'description': 'Release the runtime tool input.',
                 'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
            ]
        specs += [
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
        if (self.config.get('guides') or {}).get('enabled', True):
            specs.append(
                {'name': 'guide',
                 'description': "How a shrine or a quest is solved, from public walkthroughs (Zelda Wiki, Samurai Gamers, "
                                "IGN; English, the full solution, cached). The target is found by the game's own names: "
                                "\"current\" for the shrine Link is in or standing at (live state, then the save), or a "
                                "shrine/quest id, or its Chinese or English name. Returns the official Chinese and English "
                                "names and each source's text with its URL. Use it before explaining a puzzle; never solve "
                                "one from a picture alone. Retell only as much as the hint tier allows.",
                 'inputSchema': {'type': 'object', 'properties': {
                     'target': {'type': 'string', 'description': 'current (default), an id such as Dungeon045, or a name'}},
                     'additionalProperties': False}})
        if self.memory:
            specs.append(
                {'name': 'memory',
                 'description': "The assistant's memory of this player, kept across requests and game sessions. recall: "
                                "earlier questions and answers and the notes kept, optionally only those with the given "
                                "words or about a place id. note: keep one short sentence worth knowing next time (the "
                                "player's stated preferences, e.g. only directions; what they already know or did). "
                                "forget: drop a note by its id. Not for the game's state, which the other tools read.",
                 'inputSchema': {'type': 'object', 'properties': {
                     'action': {'type': 'string', 'enum': ['recall', 'note', 'forget']},
                     'text': {'type': 'string', 'description': 'recall: words to look for; note: the sentence to keep'},
                     'about': {'type': 'string', 'description': 'a place or quest id it concerns, e.g. Dungeon045'},
                     'id': {'type': 'string', 'description': 'forget: the note id'}},
                     'required': ['action'], 'additionalProperties': False}})
        if self.marks and self.scene_size:
            specs.append(scenemod.TOOL)
        if self.allow_screenshot:
            specs.append({'name': 'screenshot',
                          'description': 'Capture the game window now (the player allowed it for this hint). Returns the '
                                         'picture; use it when the save alone cannot tell what the player is looking at.',
                          'inputSchema': {'type': 'object', 'properties': {}, 'additionalProperties': False}})
        return specs

    def call(self, name, arguments=None):
        """Run a tool: (JSON text, image path or None). Raises ToolError for answers the model should see as errors."""
        args = dict(arguments or {})
        if name in ('press_button', 'stop_action') and not self.allow_actions:
            raise ToolError('玩家没有允许这次求助操作游戏')
        if name in ('runtime_state', 'press_button', 'stop_action', 'wait_state'):
            from .live import call
            op = {'runtime_state': 'state', 'press_button': 'press', 'stop_action': 'stop', 'wait_state': 'wait'}[name]
            try:
                result = call(op, args.get('button'), args.get('duration_ms', 150))
            except (ValueError, TimeoutError, OSError) as e:
                raise ToolError(str(e)) from e
            if isinstance(result, dict) and isinstance(result.get('state'), dict):
                view = live_view(result['state'])
                for entry in view.get('nearby') or ():
                    try:
                        zh = self.actor_name(entry['name'])
                    except Exception:   # the tables are a nicety here too
                        zh = None
                    if zh:
                        entry['name_zh'] = zh   # the game's own name: the guessed gloss is then not needed
                        entry.pop('gloss', None)
                if view.get('position') and 'scene_guess' not in view:   # world coordinates: name the place
                    try:
                        view['near_places'] = self.places.near(view['position'], limit=2)
                    except Exception:   # the place tables are a nicety here, never the reason a live read fails
                        pass
                result = dict(result, state=view)
            image = None
        elif name == 'game_state':
            result, image = self.game_state(args.get('slot')), None
        elif name == 'quest_log':
            result, image = self.quest_log(args.get('query'), bool(args.get('include_completed')), args.get('limit') or 12,
                                           args.get('slot')), None
        elif name == 'search_text':
            result, image = self.search_text(args.get('query'), args.get('limit') or 10), None
        elif name == 'guide':
            result, image = self.guide(args.get('target')), None
        elif name == 'memory':
            result, image = self.memory_tool(args.get('action'), args.get('text'), args.get('about'), args.get('id')), None
        elif name == 'screenshot':
            result, image = self.screenshot()
        elif name == 'mark_screen':
            if not (self.marks and self.scene_size):
                raise ToolError('玩家没有点“指给我看”，这次不能在画面上标注')
            try:
                result, image = scenemod.mark(args, *self.scene_size, self.marks), None
            except ValueError as e:
                raise ToolError(str(e)) from None
        else:
            raise ToolError(f'unknown tool {name}')
        return json.dumps(result, ensure_ascii=False), image


def image_block(path):
    """(media type, base64) of a screenshot file."""
    data = Path(path).read_bytes()
    return ('image/jpeg' if str(path).endswith('.jpg') else 'image/png'), base64.b64encode(data).decode()


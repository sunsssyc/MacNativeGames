"""Read-only reader for Tears of the Kingdom saves: progress.sav (all save flags) and caption.sav (what the save list
shows: time, place, picture).

Layout (1.0.0, 1.1.2, 1.2.1 and 1.4.x alike; scripts/diag/save_position.py reads the same table): magic 0x01020304, a
layout word at 4 (0x0046C3C8 1.0.0, 0x0047E0F4 1.1.2/1.2.1, 0x0049E946 1.4.x), the offset of the data area at 8, and
from 0x28 up to the data area a table of (u32 murmur3 hash of the flag name, u32 value) pairs grouped by type. A pair
with hash 0 starts the next type group (its value is the type's index in TYPES; in progress.sav the last pair, hash
0xA3DB7114, is in the Bool64bitKey group and points at its bit field; caption.sav uses the same table). Bool, Int,
UInt, Float and Enum (the murmur3 hash of the value's name) values are stored in the pair; every other type's value is
the file offset of its data (arrays: u32 count, then the elements). The game's own names for the flags only exist as
hashes in the save and in GameDataList, so readers look flags up by hashing the name.

This module never writes; the hint assistant only reads the newest slot."""
import datetime
import os
import struct
from pathlib import Path

from .formats import murmur3

TYPES = ['Bool', 'BoolArray', 'Int', 'IntArray', 'Float', 'FloatArray', 'Enum', 'EnumArray', 'Vector2', 'Vector2Array',
         'Vector3', 'Vector3Array', 'String16', 'String16Array', 'String32', 'String32Array', 'String64', 'String64Array',
         'Binary', 'BinaryArray', 'UInt', 'UIntArray', 'Int64', 'Int64Array', 'UInt64', 'UInt64Array', 'WString16',
         'WString16Array', 'WString32', 'WString32Array', 'WString64', 'WString64Array', 'Bool64bitKey']
MAGIC = 0x01020304
LAYOUTS = {0x0046C3C8: '1.0.0', 0x0047E0F4: '1.1.2 / 1.2.1', 0x0049E946: '1.4.x'}
# caption.sav flags (no names known; identified by type and value range on 1.4.x saves): the save time and the place
CAPTION_TIME = (('year', 0x9811A3F7, 2000, 2200), ('month', 0xDFD840D3, 1, 12), ('day', 0xBD46F485, 1, 31),
                ('hour', 0x23F3D75E, 0, 23), ('minute', 0x5EE50BED, 0, 59), ('second', 0x27853BF7, 0, 59))
CAPTION_POSITION, CAPTION_PLACE, CAPTION_MAP_UNITS = 0x8B26618E, 0xF74E0E8E, 0x47C0901E
SAVE_ROOT = Path.home() / 'Library/Application Support/MacNativeGames/TOTK/profile/save'
SLOT_TIE_SECONDS = 2.0   # slots copied together (an import) have the same file time: then the save's own time decides


def _f32(raw):
    return struct.unpack('<f', struct.pack('<I', raw))[0]


def _i32(raw):
    return raw - (1 << 32) if raw & 0x80000000 else raw


class SaveData:
    def __init__(self, data, path=None):
        if len(data) < 0x30 or struct.unpack_from('<I', data)[0] != MAGIC:
            raise ValueError(f'{path or "save"}: not a Tears of the Kingdom save file')
        self.data, self.path = data, path
        self.layout, end = struct.unpack_from('<II', data, 4)
        if not (0x28 < end <= len(data) and (end - 0x28) % 8 == 0):
            raise ValueError(f'{path or "save"}: damaged header (data area at {end:#x})')
        self.table = {}
        kind = 0
        for offset in range(0x28, end, 8):
            h, v = struct.unpack_from('<II', data, offset)
            if h == 0:
                if v >= len(TYPES):
                    raise ValueError(f'{path or "save"}: unknown type group {v}')
                kind = v
                continue
            self.table[h] = (TYPES[kind], v)

    @property
    def version(self):
        return LAYOUTS.get(self.layout, f'unknown layout {self.layout:#x}')

    def entry(self, name):
        """(type, raw value) of a flag given by name (or hash), or None when the save does not have it."""
        return self.table.get(name if isinstance(name, int) else murmur3(name))

    def _typed(self, name, *kinds):
        e = self.entry(name)
        return e[1] if e and e[0] in kinds else None

    def _offset(self, name, kind, size):
        at = self._typed(name, kind)
        if at is None or at + size > len(self.data):
            return None
        return at

    def bool(self, name):
        v = self._typed(name, 'Bool')
        return None if v is None else bool(v)

    def int(self, name):
        v = self._typed(name, 'Int')
        return None if v is None else _i32(v)

    def uint(self, name):
        return self._typed(name, 'UInt')

    def float(self, name):
        v = self._typed(name, 'Float')
        return None if v is None else _f32(v)

    def enum(self, name, values):
        """The enum flag's value name (values: hash -> name, from GameDataList), or its hash in hex when unknown."""
        v = self._typed(name, 'Enum')
        return None if v is None else values.get(v, f'{v:#010x}')

    def vec3(self, name):
        at = self._offset(name, 'Vector3', 12)
        return None if at is None else list(struct.unpack_from('<3f', self.data, at))

    def string(self, name):
        for kind, size in (('String64', 64), ('String32', 32), ('String16', 16)):
            at = self._offset(name, kind, size)
            if at is not None:
                return self.data[at:at + size].split(b'\0')[0].decode('utf-8', 'replace')
        return None

    def _array(self, name, kind, item):
        at = self._offset(name, kind, 4)
        if at is None:
            return None
        n = struct.unpack_from('<I', self.data, at)[0]
        if n > 100000 or at + 4 + n * item > len(self.data):
            return None
        return at + 4, n

    def ints(self, name):
        found = self._array(name, 'IntArray', 4) or self._array(name, 'UIntArray', 4)
        return None if not found else list(struct.unpack_from(f'<{found[1]}i', self.data, found[0]))

    def strings(self, name):
        found = self._array(name, 'String64Array', 64)
        if not found:
            return None
        at, n = found
        return [self.data[at + 64 * i:at + 64 * (i + 1)].split(b'\0')[0].decode('utf-8', 'replace') for i in range(n)]


class Caption:
    """caption.sav: when the save was made, the place name the save list shows, the world position (also inside a
    shrine, where progress.sav holds the shrine's own coordinates) and the map units that were loaded."""

    def __init__(self, data, path=None):
        save = SaveData(data, path)
        self.place = save.string(CAPTION_PLACE)
        self.position = save.vec3(CAPTION_POSITION)
        self.map_units = save.strings(CAPTION_MAP_UNITS) or []
        parts = {}
        for field, h, lo, hi in CAPTION_TIME:
            v = save.int(h)
            if v is None or not lo <= v <= hi:
                parts = None
                break
            parts[field] = v
        try:
            self.saved_at = datetime.datetime(**parts) if parts else None
        except ValueError:
            self.saved_at = None

    @property
    def layer(self):
        """'sky', 'ground' or 'depths' from the loaded map units (S_ sky, G_ ground, M_ / U_ depths), or None."""
        prefixes = {u[:2] for u in self.map_units if len(u) > 2 and u[1] == '_'}
        for prefix, layer in (('S_', 'sky'), ('G_', 'ground'), ('M_', 'depths'), ('U_', 'depths')):
            if prefixes == {prefix}:
                return layer
        return None


class Slot:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.progress = self.folder / 'progress.sav'
        self.mtime = self.progress.stat().st_mtime
        self._caption = False

    @property
    def caption(self):
        if self._caption is False:
            try:
                self._caption = Caption((self.folder / 'caption.sav').read_bytes(), self.folder / 'caption.sav')
            except (OSError, ValueError):
                self._caption = None
        return self._caption

    def load(self):
        return SaveData(self.progress.read_bytes(), self.progress)

    def __repr__(self):
        return f'Slot({self.folder})'


def save_roots(explicit=None, config=None):
    """Folders holding <user id>/slot_NN: --save-root / TOTK_HINT_SAVE_ROOT / assistant.json "save_root" /
    TOTK_PROFILE_DIR/save (a test profile) / the player's profile."""
    for value in (explicit, os.environ.get('TOTK_HINT_SAVE_ROOT'), (config or {}).get('save_root')):
        if value:
            return [Path(value).expanduser()]
    if os.environ.get('TOTK_PROFILE_DIR'):
        return [Path(os.environ['TOTK_PROFILE_DIR']) / 'save']
    return [SAVE_ROOT]


def slots(roots):
    out = []
    for root in roots:
        # root may itself be a user folder (holding slot_NN) or hold user folders
        for folder in sorted(list(Path(root).glob('slot_*')) + list(Path(root).glob('*/slot_*'))):
            if (folder / 'progress.sav').is_file():
                try:
                    out.append(Slot(folder))
                except OSError:
                    pass
    return out


def newest(roots):
    """The slot of the game being played: the newest progress.sav by file time; slots written within SLOT_TIE_SECONDS
    of the newest (copied together, e.g. imported from another emulator) are decided by the time the game stored in
    caption.sav."""
    found = slots(roots)
    if not found:
        raise FileNotFoundError('no save found in ' + ', '.join(map(str, roots)))
    latest = max(s.mtime for s in found)
    tied = [s for s in found if latest - s.mtime <= SLOT_TIE_SECONDS]
    if len(tied) == 1:
        return tied[0]
    floor = datetime.datetime.min
    return max(tied, key=lambda s: ((s.caption.saved_at if s.caption and s.caption.saved_at else floor), s.mtime))

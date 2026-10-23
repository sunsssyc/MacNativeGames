"""Readers for the Tears of the Kingdom data formats the hint assistant needs, standard library only (Python 3.14):

- zstd with the game's dictionaries (Pack/ZsDic.pack.zs, as scripts/make_romfs_patches.py loads them),
- SARC archives,
- BYML v2-v7 in either byte order (the RSDB tables and location files are little-endian, GameData/GameDataList is
  big-endian),
- MSBT message files, with the control tags turned into plain text,
- the 32-bit murmur3 hash (seed 0) the game uses for the names of its save flags ("PlayerStatus.SavePos" -> 0xc884818d).

Nothing here writes anything; game data stays where it is."""
import struct

try:
    import compression.zstd as zstd   # Python 3.14
except ImportError:   # pragma: no cover - only the RomFS readers need it
    zstd = None


def murmur3(data, seed=0):
    """MurmurHash3 x86 32-bit of a str (UTF-8) or bytes."""
    if isinstance(data, str):
        data = data.encode()
    c1, c2, mask = 0xcc9e2d51, 0x1b873593, 0xffffffff
    h = seed & mask
    n = len(data)
    tail = n & ~3
    for i in range(0, tail, 4):
        k = int.from_bytes(data[i:i + 4], 'little')
        k = (k * c1) & mask
        k = ((k << 15) | (k >> 17)) & mask
        k = (k * c2) & mask
        h ^= k
        h = ((h << 13) | (h >> 19)) & mask
        h = (h * 5 + 0xe6546b64) & mask
    k = 0
    rest = n & 3
    if rest == 3:
        k ^= data[tail + 2] << 16
    if rest >= 2:
        k ^= data[tail + 1] << 8
    if rest >= 1:
        k ^= data[tail]
        k = (k * c1) & mask
        k = ((k << 15) | (k >> 17)) & mask
        k = (k * c2) & mask
        h ^= k
    h ^= n
    h ^= h >> 16
    h = (h * 0x85ebca6b) & mask
    h ^= h >> 13
    h = (h * 0xc2b2ae35) & mask
    h ^= h >> 16
    return h


def sarc_members(data):
    """name -> (absolute start, end) of every member of a little-endian SARC archive."""
    if data[:4] != b'SARC' or data[6:8] != b'\xff\xfe':
        raise ValueError('not a little-endian SARC archive')
    header, size, start = struct.unpack_from('<HxxII', data, 4)
    if size != len(data) or data[header:header + 4] != b'SFAT':
        raise ValueError('damaged SARC archive')
    count = struct.unpack_from('<H', data, header + 6)[0]
    names = header + 12 + count * 16
    if data[names:names + 4] != b'SFNT':
        raise ValueError('SARC archive without a name table')
    names += 8
    out = {}
    for i in range(count):
        _, attribute, lo, hi = struct.unpack_from('<4I', data, header + 12 + i * 16)
        if not attribute >> 24:   # no stored name: the member is only known by its hash
            continue
        offset = names + (attribute & 0xffffff) * 4
        out[data[offset:data.index(0, offset, start)].decode()] = (start + lo, start + hi)
    return out


class ZstdDictionaries:
    """The game's zstd dictionaries (Pack/ZsDic.pack.zs: a plain zstd frame holding a SARC of *.zsdic files)."""

    def __init__(self, pack_zs):
        if zstd is None:
            raise RuntimeError('Python 3.14 or newer is needed (compression.zstd)')
        pack = zstd.decompress(pack_zs)
        self.by_id = {}
        for lo, hi in sarc_members(pack).values():
            d = zstd.ZstdDict(pack[lo:hi])
            self.by_id[d.dict_id] = d

    def decompress(self, raw):
        info = zstd.get_frame_info(raw)
        if info.dictionary_id:
            if info.dictionary_id not in self.by_id:
                raise ValueError(f'zstd frame needs dictionary {info.dictionary_id}, which Pack/ZsDic.pack.zs does not have')
            return zstd.decompress(raw, zstd_dict=self.by_id[info.dictionary_id])
        return zstd.decompress(raw)


class Byml:
    """BYML v2-v7 reader. Values: str, bytes, bool, int, float, None, list, dict. Containers can also be walked one level
    at a time (items / elements) so a large file (GameDataList: 165,000 flag entries) need not be decoded whole."""
    STRING, BINARY, ARRAY, DICT, STRINGS = 0xa0, 0xa1, 0xc0, 0xc1, 0xc2

    def __init__(self, data):
        if data[:2] == b'YB':
            self.e = '<'
        elif data[:2] == b'BY':
            self.e = '>'
        else:
            raise ValueError('not a BYML document')
        self.d = data
        self.version, keys, strings, root = struct.unpack_from(self.e + 'HIII', data, 2)
        if not 2 <= self.version <= 7:
            raise ValueError(f'BYML version {self.version} is not supported')
        self.keys = self._strings(keys)
        self.strings = self._strings(strings)
        self.root_offset = root

    def _u32(self, off):
        return struct.unpack_from(self.e + 'I', self.d, off)[0]

    def _header(self, off):
        """(node type, 24-bit count) of the container at off."""
        word = self._u32(off)
        return self.d[off], (word >> 8 if self.e == '<' else word & 0xffffff)

    def _strings(self, off):
        if not off:
            return []
        kind, n = self._header(off)
        if kind != self.STRINGS:
            raise ValueError(f'BYML string table has node type {kind:#x}')
        offs = struct.unpack_from(f'{self.e}{n + 1}I', self.d, off + 4)
        return [self.d[off + offs[i]:off + offs[i + 1] - 1].decode('utf-8', 'replace') for i in range(n)]

    def items(self, off):
        """[(key, node type, raw value)] of the dictionary at off."""
        kind, n = self._header(off)
        if kind != self.DICT:
            raise ValueError(f'BYML node at {off:#x} is {kind:#x}, not a dictionary')
        out = []
        for i in range(n):
            entry = off + 4 + i * 8
            word = self._u32(entry)
            key = word & 0xffffff if self.e == '<' else word >> 8
            out.append((self.keys[key], self.d[entry + 3], self._u32(entry + 4)))
        return out

    def elements(self, off):
        """[(node type, raw value)] of the array at off."""
        kind, n = self._header(off)
        if kind != self.ARRAY:
            raise ValueError(f'BYML node at {off:#x} is {kind:#x}, not an array')
        types = self.d[off + 4:off + 4 + n]
        values = off + 4 + ((n + 3) & ~3)
        return [(types[i], self._u32(values + i * 4)) for i in range(n)]

    def value(self, kind, raw):
        e, d = self.e, self.d
        if kind == self.STRING:
            return self.strings[raw]
        if kind == self.BINARY:
            return bytes(d[raw + 4:raw + 4 + self._u32(raw)])
        if kind == self.ARRAY:
            return [self.value(k, v) for k, v in self.elements(raw)]
        if kind == self.DICT:
            return {key: self.value(k, v) for key, k, v in self.items(raw)}
        if kind == 0xd0:
            return bool(raw)
        if kind == 0xd1:
            return raw - (1 << 32) if raw & 0x80000000 else raw
        if kind == 0xd2:
            return struct.unpack('<f', struct.pack('<I', raw))[0]
        if kind == 0xd3:
            return raw
        if kind == 0xd4:
            return struct.unpack_from(e + 'q', d, raw)[0]
        if kind == 0xd5:
            return struct.unpack_from(e + 'Q', d, raw)[0]
        if kind == 0xd6:
            return struct.unpack_from(e + 'd', d, raw)[0]
        if kind == 0xff:
            return None
        raise ValueError(f'BYML node type {kind:#x} is not supported')

    def root_kind(self):
        return self.d[self.root_offset]

    def root(self):
        return self.value(self.root_kind(), self.root_offset)


def byml(data):
    return Byml(data).root()


# MSBT control tags (UTF-16: 0x0e group type size params..., 0x0f group type closes a tag). Group 0 type 3 is a text
# colour: the highlighted words of a quest log ("<color>希多</color>") become 【希多】. Group 2 inserts a value the
# game fills in at run time (a count, an item name): shown as "…". Group 1 type 4 is a button or icon glyph.
# Everything else (font size, voice, animation, pauses) is dropped.
OPEN_MARK, CLOSE_MARK, VALUE_MARK, ICON_MARK = '【', '】', '…', '〔按键〕'


def _render(units, e):
    out = []
    colored = False
    p, n = 0, len(units)
    while p + 1 < n:
        c = struct.unpack_from(e + 'H', units, p)[0]
        p += 2
        if c == 0:
            break
        if c == 0x0e:
            if p + 6 > n:
                break
            group, kind, size = struct.unpack_from(e + 'HHH', units, p)
            params = units[p + 6:p + 6 + size]
            p += 6 + size
            if group == 0 and kind == 3:
                closing = params[:2] == b'\xff\xff'
                if closing and colored:
                    out.append(CLOSE_MARK)
                    colored = False
                elif not closing:
                    if colored:
                        out.append(CLOSE_MARK)
                    out.append(OPEN_MARK)
                    colored = True
            elif group == 2:
                out.append(VALUE_MARK)
            elif group == 1 and kind == 4:
                out.append(ICON_MARK)
        elif c == 0x0f:
            p += 4
        else:
            out.append(chr(c))
    if colored:
        out.append(CLOSE_MARK)
    # surrogate pairs come out as two chr() values: join them properly
    return ''.join(out).encode('utf-16', 'surrogatepass').decode('utf-16', 'replace')


def msbt(data):
    """label -> text of an MSBT file (UTF-16 or UTF-8), control tags rendered as described above."""
    if data[:8] != b'MsgStdBn':
        raise ValueError('not an MSBT file')
    e = '<' if data[8:10] == b'\xff\xfe' else '>'
    encoding = data[0x0c]
    count = struct.unpack_from(e + 'H', data, 0x0e)[0]
    pos, sections = 0x20, {}
    for _ in range(count):
        name = data[pos:pos + 4]
        size = struct.unpack_from(e + 'I', data, pos + 4)[0]
        sections[name] = data[pos + 0x10:pos + 0x10 + size]
        pos += 0x10 + ((size + 15) & ~15)
    labels_section, texts_section = sections.get(b'LBL1'), sections.get(b'TXT2')
    if labels_section is None or texts_section is None:
        raise ValueError('MSBT without LBL1 / TXT2')
    labels = {}
    for g in range(struct.unpack_from(e + 'I', labels_section, 0)[0]):
        n, off = struct.unpack_from(e + 'II', labels_section, 4 + g * 8)
        for _ in range(n):
            length = labels_section[off]
            name = labels_section[off + 1:off + 1 + length].decode('utf-8', 'replace')
            labels[struct.unpack_from(e + 'I', labels_section, off + 1 + length)[0]] = name
            off += 1 + length + 4
    n = struct.unpack_from(e + 'I', texts_section, 0)[0]
    offsets = struct.unpack_from(f'{e}{n}I', texts_section, 4)
    out = {}
    for i in range(n):
        raw = texts_section[offsets[i]:offsets[i + 1] if i + 1 < n else len(texts_section)]
        if encoding == 1:
            text = _render(raw, e)
        else:   # UTF-8 files: no tag table here, drop control characters
            text = ''.join(ch for ch in raw.split(b'\0')[0].decode('utf-8', 'replace') if ch >= ' ' or ch == '\n')
        out[labels.get(i, str(i))] = text
    return out

"""Read-only access to the game's RomFS image (romfs.bin) through its index.

Two index formats exist: the app's runtime-index.bin ("TOTKRFS1", written by scripts/prepare_romfs_backend.py, inside
Tears of the Kingdom.app/Contents/Resources/totk/extracted/<version>/romfs) and the build work folder's index.json
(TOTK_build/totk/extracted/<version>/romfs). Either is enough."""
import fnmatch
import json
import os
import struct
from pathlib import Path

from .formats import ZstdDictionaries

DATA_DIR = Path.home() / 'Library/Application Support/MacNativeGames/TOTK'


def outside_image(folder):
    """romfs.bin kept outside the app, for an index folder that has none: TOTK_ROMFS_DATA (the launcher sets it for the
    game and the hint service it starts), else the Info.plist MNGGameData of the app the folder is in (a development
    build made with build_app.py --game-data-outside; app/launcher.m)."""
    if os.environ.get('TOTK_ROMFS_DATA'):
        return Path(os.environ['TOTK_ROMFS_DATA']) / 'romfs.bin'
    for parent in Path(folder).resolve().parents:
        if parent.name == 'Contents' and (parent / 'Info.plist').is_file():
            import plistlib
            try:
                data = plistlib.loads((parent / 'Info.plist').read_bytes()).get('MNGGameData')
            except (OSError, ValueError):
                return None
            return Path(data) / 'romfs.bin' if isinstance(data, str) and data else None
    return None


class RomFS:
    def __init__(self, folder):
        self.folder = Path(folder).expanduser()
        self.image = self.folder / 'romfs.bin'
        if not self.image.is_file():
            self.image = outside_image(self.folder) or self.image
        if not self.image.is_file():
            raise FileNotFoundError(f'{self.image}: no RomFS image')
        if not any((self.folder / name).is_file() for name in ('runtime-index.bin', 'index.json')):
            raise FileNotFoundError(f'{self.folder}: no runtime-index.bin or index.json')
        self._files = None
        self._zstd = None

    @property
    def files(self):
        """path -> (offset, size)."""
        if self._files is None:
            binary = self.folder / 'runtime-index.bin'
            self._files = read_runtime_index(binary) if binary.is_file() else read_index_json(self.folder / 'index.json')
        return self._files

    def identity(self):
        """A short string that changes when the image changes (size of the image and of its index)."""
        index = self.folder / ('runtime-index.bin' if (self.folder / 'runtime-index.bin').is_file() else 'index.json')
        image_stat, index_stat = self.image.stat(), index.stat()
        return f'{image_stat.st_size}-{image_stat.st_mtime_ns}-{index_stat.st_size}-{index_stat.st_mtime_ns}'

    def find(self, pattern):
        return sorted(p for p in self.files if fnmatch.fnmatchcase(p, pattern))

    def read(self, path):
        offset, size = self.files[path]
        with self.image.open('rb') as f:
            f.seek(offset)
            data = f.read(size)
        if len(data) != size:
            raise ValueError(f'{path}: RomFS image ends early')
        return data

    def read_zs(self, path):
        """A .zs file decompressed with the game's dictionaries."""
        if self._zstd is None:
            self._zstd = ZstdDictionaries(self.read('Pack/ZsDic.pack.zs'))
        return self._zstd.decompress(self.read(path))


def read_runtime_index(path):
    data = Path(path).read_bytes()
    magic, count, strings = struct.unpack_from('<8sQQ', data, 0)
    if magic != b'TOTKRFS1' or strings != 24 + count * 24 or strings > len(data):
        raise ValueError(f'{path}: not a RomFS index')
    files = {}
    for i in range(count):
        offset, size, name, length = struct.unpack_from('<QQII', data, 24 + i * 24)
        files[data[strings + name:strings + name + length - 1].decode()] = (offset, size)
    return files


def read_index_json(path):
    index = json.loads(Path(path).read_text())
    return {f['path']: (f['offset'], f['size']) for f in index['files']}


def _candidates(explicit=None, config=None):
    if explicit:
        yield Path(explicit)
    if os.environ.get('TOTK_HINT_ROMFS'):
        yield Path(os.environ['TOTK_HINT_ROMFS'])
    if config and config.get('romfs'):
        yield Path(config['romfs'])
    # inside the app: <app>/Contents/Resources/totk/hint_assistant/totk_hint/romfs.py
    here = Path(__file__).resolve()
    for parent in here.parents:
        if parent.name == 'totk' and parent.parent.name == 'Resources':
            yield from sorted((parent / 'extracted').glob('v*/romfs'), reverse=True)
            break
    # the app the player last started: the game slot records its folder (runtime/game_slot.c, app/launcher.m)
    holder = DATA_DIR / 'game-slot/holder'
    try:
        for line in holder.read_text().splitlines():
            if line.startswith('cwd='):
                yield from sorted((Path(line[4:]) / 'extracted').glob('v*/romfs'), reverse=True)
    except OSError:
        pass
    for app in (Path('/Applications/Tears of the Kingdom.app'), Path.home() / 'Applications/Tears of the Kingdom.app'):
        yield from sorted((app / 'Contents/Resources/totk/extracted').glob('v*/romfs'), reverse=True)


def find_romfs(explicit=None, config=None):
    """The first usable RomFS folder: --romfs / TOTK_HINT_ROMFS / assistant.json "romfs" / the app this code is in / the
    app the game slot names / the usual app locations."""
    tried = []
    for folder in _candidates(explicit, config):
        folder = folder.expanduser()
        if folder in tried:
            continue
        tried.append(folder)
        try:
            return RomFS(folder)
        except (OSError, ValueError):
            continue
    raise FileNotFoundError('no game data (RomFS) found; tried: ' + ', '.join(map(str, tried)) if tried else
                            'no game data (RomFS) found: pass --romfs <TOTK_build/totk/extracted/v143/romfs> or set "romfs" in assistant.json')

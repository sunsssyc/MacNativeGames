"""攻略: how a shrine (or a quest, a place) is solved, from public guides, found by the game's own English name.

Guessing a puzzle from one frame goes wrong (2026-10-24: light falling from above became "a glowing fragment"); the
guides agree with each other and with the objects the game reports. Pages are found by URL, not by a search engine:
    Zelda Wiki       zeldawiki.wiki MediaWiki API (wikitext): layout, Zonai devices, where the chest is
    Samurai Gamers   samurai-gamers.com/zelda-tears-of-the-kingdom/<name>-walkthrough/: numbered steps
    IGN              ign.com/wikis/the-legend-of-zelda-tears-of-the-kingdom/<Name>: a walkthrough in prose
The English name comes from the game's own text (Mals/USen); a Chinese guide's name for a shrine is often not the
game's. Zelda Dungeon's wiki sits behind a Cloudflare challenge and is not used. Fetched pages are cached for 30 days
under the cache folder; a source that does not answer within the timeout is left out."""
import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from . import tables as tablemod

CACHE = tablemod.CACHE_ROOT / 'guides'
MAX_AGE = 30 * 86400
MAX_CHARS = 3000   # per source, for the model's context
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15'


def _get(url, timeout):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept-Language': 'en'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode('utf-8', 'replace')


def _page_text(document, start, end):
    """Readable text of the part of an HTML page between two patterns."""
    m = re.search(start, document)
    if not m:
        return ''
    e = re.search(end, document[m.end():])
    body = document[m.start(): m.end() + e.start()] if e else document[m.start():]
    body = re.sub(r'(?is)<(script|style|noscript|svg|figure|iframe|aside)\b.*?</\1>', ' ', body)
    body = re.sub(r'(?i)<br\s*/?>|</p>|</li>|</h\d>|</tr>', '\n', body)
    body = html.unescape(re.sub(r'<[^>]+>', ' ', body))
    body = re.sub(r'[ \t\xa0]+', ' ', body)
    return re.sub(r'\n\s*\n+', '\n', body).strip()


def _wikitext(text):
    """Zelda Wiki markup as plain text: templates, references and files out, links as their words."""
    text = re.sub(r'(?s)<ref[^>]*/>|<ref[^>]*>.*?</ref>', '', text)
    text = re.sub(r'\{\{Term/Store\|([^|}]*)[^}]*\}\}', r'\1', text)
    text = re.sub(r'\{\{(?:Big|Color TotK\|[^|}]*)\|([^{}]*)\}\}', r'\1', text)
    for _ in range(4):   # nested templates, innermost first
        text = re.sub(r'\{\{[^{}]*\}\}', '', text)
    text = re.sub(r'\[\[(?:File|Image|Category):[^\]]*\]\]', '', text)
    text = re.sub(r'\[\[[^\]|]*\|([^\]]*)\]\]', r'\1', text)
    text = re.sub(r'\[\[([^\]]*)\]\]', r'\1', text)
    text = re.sub(r"'{2,}", '', text)
    text = re.sub(r'(?s)<gallery>.*?</gallery>', '', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\n\s*\n+', '\n', text).strip()


def _zeldawiki(name, timeout):
    title = urllib.parse.quote(name.replace(' ', '_'))
    url = f'https://zeldawiki.wiki/w/api.php?action=parse&page={title}&prop=wikitext&format=json&formatversion=2'
    data = json.loads(_get(url, timeout))
    if 'parse' not in data:
        return None
    return f'https://zeldawiki.wiki/wiki/{title}', _wikitext(data['parse']['wikitext'])


def _samurai(name, timeout):
    slug = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
    url = f'https://samurai-gamers.com/zelda-tears-of-the-kingdom/{slug}-walkthrough/'
    text = _page_text(_get(url, timeout), r'(?i)<div class="entry-content', r'(?i)<footer|class="comment')
    text = re.sub(r'(?s)^.*?(?=\b\S+ (?:Shrine )?Walkthrough for)', '', text, count=1)   # past the boilerplate intro
    return url, text


def _ign(name, timeout):
    url = f'https://www.ign.com/wikis/the-legend-of-zelda-tears-of-the-kingdom/{urllib.parse.quote(name.replace(" ", "_"))}'
    return url, _page_text(_get(url, timeout), r'(?i)<h2[^>]*>(?:<[^>]+>)*[^<]*Walkthrough', r'(?i)Up Next|Was this guide helpful|Click or tap here to return')


SOURCES = (('Zelda Wiki', _zeldawiki), ('Samurai Gamers', _samurai), ('IGN', _ign))


def fetch(name, timeout=8.0, cache=None, sources=SOURCES):
    """[{"source", "url", "text"}] for an English name, from the cache when fresh, else fetched from every source at once."""
    cache = Path(cache) if cache else CACHE
    path = cache / (re.sub(r'[^A-Za-z0-9]+', '_', name).strip('_') + '.json')
    try:
        cached = json.loads(path.read_text(encoding='utf-8'))
        if time.time() - cached['time'] < MAX_AGE and cached['pages']:
            return cached['pages']
    except (OSError, ValueError, KeyError):
        pass
    pages, lock = {}, threading.Lock()

    def one(label, get):
        try:
            got = get(name, timeout)
        except urllib.error.HTTPError as e:
            e.close()
            return   # a missing page (404) or a block (403): the others still count
        except (urllib.error.URLError, OSError, ValueError, KeyError):
            return   # a slow or unreachable site
        if got and len(got[1]) > 200:
            with lock:
                pages[label] = {'source': label, 'url': got[0], 'text': got[1][:MAX_CHARS]}
    threads = [threading.Thread(target=one, args=source, daemon=True) for source in sources]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout + 2)
    result = [pages[label] for label, _ in sources if label in pages]
    if result:
        cache.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'time': time.time(), 'pages': result}, ensure_ascii=False), encoding='utf-8')
    return result

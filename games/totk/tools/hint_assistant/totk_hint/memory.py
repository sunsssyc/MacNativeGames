"""记忆和历史对话: what the assistant keeps between requests and between game sessions, in one SQLite database next to
the game's other files (assistant.db; never in the repository). Every channel shares it: the service writes it and puts
the relevant part into each prompt, and the tools read it, in the service itself or in the MCP server an agent starts.
    turns   every question and answer in full: when, which game run and panel session, the tier, the channel and model
            that answered, where Link was (a shrine's id from the save). The service writes one after every answer.
    notes   what the model chose to remember with the memory tool: the player's preferences ("只要方向"), what they
            already know or did. At most a sentence each.
A request's prompt carries the few that matter (context()): every note, the turns about the same place, the latest
turns. The history tool reads whole conversations back. The database is shared by processes, so it runs in WAL mode;
the oldest turns go beyond MAX_TURNS. An assistant-memory.json from before (the first version) is read in once and kept
renamed as .migrated."""
import json
import sqlite3
import time
import uuid
from pathlib import Path

from .romfs import DATA_DIR

PATH = DATA_DIR / 'assistant.db'
LEGACY = 'assistant-memory.json'
MAX_TURNS = 5000
MAX_NOTES = 60
NOTE_CHARS = 120
CONTEXT_CHARS = 120   # an earlier answer in the prompt: its first line, cut here
SCHEMA = """
CREATE TABLE IF NOT EXISTS turns (id INTEGER PRIMARY KEY, time REAL NOT NULL, run TEXT, session TEXT, tier INTEGER,
    question TEXT, answer TEXT NOT NULL, backend TEXT, model TEXT, place_id TEXT, place_name TEXT, seconds REAL);
CREATE INDEX IF NOT EXISTS turns_place ON turns (place_id);
CREATE INDEX IF NOT EXISTS turns_session ON turns (run, session);
CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, time REAL NOT NULL, text TEXT NOT NULL UNIQUE, about TEXT);
"""


def _short(text, n):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= n else text[:n - 1] + '…'


def _day(t):
    return time.strftime('%m-%d', time.localtime(t))


class Memory:
    def __init__(self, path=None):
        self.path = Path(path) if path else PATH
        self._ready = False

    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        if not self._ready:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            self._migrate(db)
            self._ready = True
        return db

    def _migrate(self, db):
        legacy = self.path.with_name(LEGACY)
        if not legacy.is_file() or db.execute('SELECT 1 FROM turns LIMIT 1').fetchone() or \
                db.execute('SELECT 1 FROM notes LIMIT 1').fetchone():
            return
        try:
            data = json.loads(legacy.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        with db:
            for a in data.get('answers') or ():
                if isinstance(a, dict) and a.get('answer'):
                    about = a.get('about') or {}
                    db.execute('INSERT INTO turns (time, run, tier, question, answer, backend, place_id, place_name) '
                               'VALUES (?, ?, ?, ?, ?, ?, ?, ?)', (a.get('time') or 0, 'migrated', a.get('tier'), a.get('question'),
                                                                  a['answer'], a.get('backend'), about.get('id'), about.get('name')))
            for n in data.get('notes') or ():
                if isinstance(n, dict) and n.get('text'):
                    db.execute('INSERT OR IGNORE INTO notes VALUES (?, ?, ?, ?)',
                               (n.get('id') or uuid.uuid4().hex[:8], n.get('time') or 0, n['text'], n.get('about')))
        legacy.rename(legacy.with_name(LEGACY + '.migrated'))

    def record_answer(self, question, tier, answer, about=None, backend=None, run=None, session=None, model=None,
                      seconds=None):
        about = about or {}
        with self._db() as db:
            db.execute('INSERT INTO turns (time, run, session, tier, question, answer, backend, model, place_id, place_name, '
                       'seconds) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                       (time.time(), run, None if session is None else str(session), tier, question or None, str(answer or ''),
                        backend, model, about.get('id'), about.get('name'), seconds))
            db.execute('DELETE FROM turns WHERE id <= (SELECT MAX(id) FROM turns) - ?', (MAX_TURNS,))

    def note(self, text, about=None):
        """Remember one sentence; a note with the same text replaces the old one. Returns its id."""
        text = _short(text, NOTE_CHARS)
        if not text:
            raise ValueError('要记住的内容是空的')
        note_id = uuid.uuid4().hex[:8]
        with self._db() as db:
            db.execute('DELETE FROM notes WHERE text = ?', (text,))
            db.execute('INSERT INTO notes VALUES (?, ?, ?, ?)', (note_id, time.time(), text, str(about)[:60] if about else None))
            db.execute('DELETE FROM notes WHERE id NOT IN (SELECT id FROM notes ORDER BY time DESC LIMIT ?)', (MAX_NOTES,))
        return note_id

    def forget(self, note_id):
        with self._db() as db:
            return db.execute('DELETE FROM notes WHERE id = ?', (note_id,)).rowcount > 0

    def notes(self):
        with self._db() as db:
            return [dict(r) for r in db.execute('SELECT * FROM notes ORDER BY time')]

    def turns(self, query=None, about=None, limit=10, run=None, session=None):
        """Turns newest first: with all the words of query in the question or the answer, about a place id, of one panel
        session."""
        sql, args = 'SELECT * FROM turns WHERE 1', []
        for word in str(query or '').split():
            sql += ' AND (question LIKE ? OR answer LIKE ? OR place_name LIKE ?)'
            args += [f'%{word}%'] * 3
        if about:
            sql += ' AND place_id = ?'
            args.append(about)
        if session is not None:
            sql += ' AND run IS ? AND session = ?'
            args += [run, str(session)]
        with self._db() as db:
            return [dict(r) for r in db.execute(sql + ' ORDER BY id DESC LIMIT ?', args + [max(1, int(limit))])]

    def conversation(self, session, limit=12):
        """The turns of one panel conversation, oldest first, whichever game run they were in: the panel's session ids
        are unique, so a conversation reopened from 历史 after a restart goes on with its earlier turns."""
        with self._db() as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM turns WHERE session = ? ORDER BY id DESC LIMIT ?',
                                                (str(session), max(1, int(limit))))]
        return list(reversed(rows))

    def conversations(self, limit=20, turns=12):
        """The latest panel conversations, newest first: [{"id", "turns": [...oldest first]}]."""
        with self._db() as db:
            ids = [r[0] for r in db.execute('SELECT session FROM turns WHERE session IS NOT NULL GROUP BY session '
                                            'ORDER BY MAX(id) DESC LIMIT ?', (max(1, int(limit)),))]
        return [{'id': i, 'turns': self.conversation(i, turns)} for i in ids]

    def recall(self, query=None, about=None, limit=12):
        """The memory tool: notes and earlier answers that mention the words of query or are about the place id `about`."""
        words = [w.lower() for w in str(query or '').split()]
        notes = [n for n in reversed(self.notes())
                 if all(w in f"{n['text']} {n.get('about') or ''}".lower() for w in words)
                 and (not about or about == n.get('about'))]
        answers = [{'time': time.strftime('%Y-%m-%d %H:%M', time.localtime(t['time'])), 'question': t['question'],
                    'answer': _short(t['answer'], 200), 'place': t['place_name'], 'channel': t['backend'], 'tier': t['tier']}
                   for t in self.turns(query, about, limit)]
        return {'notes': notes[:limit], 'answers': answers,
                'note': '记忆只存在这台 Mac 上；answers 是之前的问答（长的截断了，全文用 history 查），notes 是之前记下的玩家偏好和情况'}

    def history(self, query=None, about=None, limit=6):
        """The history tool: earlier conversations in full, newest first, each turn with its channel."""
        rows = self.turns(query, about, min(max(1, int(limit or 6)), 20))
        return {'turns': [{'time': time.strftime('%Y-%m-%d %H:%M', time.localtime(r['time'])), 'question': r['question'] or '（按了提示键）',
                           'answer': r['answer'], 'tier': r['tier'], 'place': r['place_name'], 'channel': r['backend'],
                           'model': r['model'], 'session': f"{r['run'] or '-'}/{r['session'] or '-'}"} for r in rows],
                'note': '之前在这台 Mac 上的对话，新的在前；session 相同的是同一次求助'}

    def context(self, about=None, recent=3, same_place=3, skip=None):
        """Lines for the prompt: every note, then earlier answers about the same place, then the latest answers.
        skip: the panel session whose turns the prompt already carries as this conversation."""
        lines = [f'- 记下的：{n["text"]}（{_day(n["time"])}）' for n in self.notes()[-12:]]
        seen = set()

        def fresh(rows, n):
            out = []
            for r in rows:
                if r['id'] in seen or (skip is not None and r['session'] == str(skip)):
                    continue
                seen.add(r['id'])
                out.append(r)
                if len(out) == n:
                    break
            return out
        chosen = fresh(self.turns(about=about['id'], limit=same_place + 10), same_place) if about else []
        chosen += fresh(self.turns(limit=recent + 10), recent)
        for r in chosen:
            where = r['place_name']
            asked = f'问“{_short(r["question"], 60)}”' if r['question'] else '按了提示键'
            first = _short(str(r['answer']).split('\n')[0], CONTEXT_CHARS)
            lines.append(f'- {_day(r["time"])}{" 在" + where if where else ""}{asked}（{r["tier"]} 档，{r["backend"] or "?"}）→ 答“{first}”')
        return lines

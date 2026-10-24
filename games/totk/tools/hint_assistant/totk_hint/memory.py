"""记忆: what the assistant keeps between requests and between game sessions, in assistant-memory.json next to the
game's other files (never in the repository). Two kinds:
    answers   one entry per answered question: when, where Link was (a shrine's id from the save), the tier, the
              question and the start of the answer. The service writes one after every answer.
    notes     what the model chose to remember with the memory tool: the player's preferences ("只要方向"), what they
              already know or did. At most a sentence each.
A request's prompt carries the few that matter (context()): every note, the answers about the same place, the latest
answers. The file is shared by the service and the MCP server the agents start, so writes take a lock."""
import fcntl
import json
import os
import time
import uuid
from pathlib import Path

from .romfs import DATA_DIR

PATH = DATA_DIR / 'assistant-memory.json'
MAX_ANSWERS = 200
MAX_NOTES = 60
NOTE_CHARS = 120
ANSWER_CHARS = 80


def _short(text, n):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= n else text[:n - 1] + '…'


def _day(t):
    return time.strftime('%m-%d', time.localtime(t))


class Memory:
    def __init__(self, path=None):
        self.path = Path(path) if path else PATH

    def load(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault('version', 1)
        data['answers'] = [a for a in data.get('answers') or () if isinstance(a, dict)]
        data['notes'] = [n for n in data.get('notes') or () if isinstance(n, dict) and n.get('text')]
        return data

    def _update(self, change):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_name(self.path.name + '.lock'), 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self.load()
            result = change(data)
            data['answers'] = data['answers'][-MAX_ANSWERS:]
            data['notes'] = data['notes'][-MAX_NOTES:]
            tmp = self.path.with_name(f'.{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp')
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
            tmp.replace(self.path)
            return result

    def record_answer(self, question, tier, answer, about=None, backend=None):
        entry = {'time': round(time.time()), 'tier': tier, 'question': _short(question, 60) or None,
                 'answer': _short(str(answer or '').split('\n')[0], ANSWER_CHARS)}
        if about:
            entry['about'] = {'id': about['id'], 'name': about.get('name')}
        if backend:
            entry['backend'] = backend
        self._update(lambda data: data['answers'].append(entry))

    def note(self, text, about=None):
        """Remember one sentence; a note with the same text replaces the old one. Returns its id."""
        text = _short(text, NOTE_CHARS)
        if not text:
            raise ValueError('要记住的内容是空的')
        entry = {'id': uuid.uuid4().hex[:8], 'time': round(time.time()), 'text': text}
        if about:
            entry['about'] = str(about)[:60]

        def change(data):
            data['notes'] = [n for n in data['notes'] if n['text'] != text]
            data['notes'].append(entry)
            return entry['id']
        return self._update(change)

    def forget(self, note_id):
        def change(data):
            before = len(data['notes'])
            data['notes'] = [n for n in data['notes'] if n.get('id') != note_id]
            return before != len(data['notes'])
        return self._update(change)

    def recall(self, query=None, about=None, limit=12):
        """Notes and earlier answers that mention the words of query or are about the place id `about`, newest first."""
        data = self.load()
        words = [w.lower() for w in str(query or '').split() if w]

        def hits(entry):
            hay = json.dumps(entry, ensure_ascii=False).lower()
            return (not words or all(w in hay for w in words)) and (not about or str(about).lower() in hay)
        notes = [n for n in reversed(data['notes']) if hits(n)]
        answers = [a for a in reversed(data['answers']) if hits(a)]
        return {'notes': notes[:limit], 'answers': answers[:limit],
                'note': '记忆只记在这台 Mac 上；answers 是之前的问答（只记了回答的第一行），notes 是之前记下的玩家偏好和情况'}

    def context(self, about=None, recent=3, same_place=3):
        """Lines for the prompt: every note, then earlier answers about the same place, then the latest answers."""
        data = self.load()
        lines = [f'- 记下的：{n["text"]}（{_day(n["time"])}）' for n in data['notes'][-12:]]
        answers, seen = [], set()
        if about:
            answers += [a for a in reversed(data['answers']) if (a.get('about') or {}).get('id') == about['id']][:same_place]
        answers += list(reversed(data['answers']))[:recent]
        for a in answers:
            if id(a) in seen:
                continue
            seen.add(id(a))
            where = (a.get('about') or {}).get('name')
            asked = f'问“{a["question"]}”' if a.get('question') else '按了提示键'
            lines.append(f'- {_day(a["time"])}{" 在" + where if where else ""}{asked}（{a.get("tier")} 档）→ 答“{a["answer"]}”')
        return lines

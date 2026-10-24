"""One hint (the CLI's `hint`) and the service the game talks to (`serve`).

The game (runtime/hint_overlay.m, key 8) writes hint-request.json next to its other files:
    {"id": 7, "session": 6, "tier": 0, "time": 1792737015}       tier 0: assistant.json tier_default
    {"id": 7, "session": 6, "question": "...", "actions": true}   a question the player allowed to press buttons
    {"id": 7, "session": 6, "cancel": true}                       Esc while the hint is being worked out
and shows hint-response.json:
    {"id": 7, "session": 6, "tier": 1, "status": "working"|"done"|"error"|"cancelled", "text": "...",
     "backend": "claude-code", "seconds": 12.3, "next_tier": 2, "limit": 150}
"limit" is the request's time budget in seconds (total_timeout_seconds); the game stops waiting a little after it.
A session is one stuck moment: its later tiers see the earlier answers and go one step further."""
import fcntl
import json
import os
import sys
import threading
import time
from pathlib import Path

from . import backends as backendmod
from . import config as configmod
from . import voice as voicemod
from .harness import Harness
from .prompts import SYSTEM, TIER_NAMES, clean, user_prompt
from .romfs import DATA_DIR

REQUEST = 'hint-request.json'
RESPONSE = 'hint-response.json'
MAX_HISTORY_TURNS = 12
MAX_SESSIONS = 8
MAX_QUESTION_CHARS = 2000


def hint(config, tier=None, backend='auto', question=None, previous=None, allow_screenshot=None, romfs=None,
         save_root=None, cancel=None, progress=None, scene_image=None, allow_actions=False):
    """{"text", "tier", "backend", "model", "seconds", "attempts"}; raises BackendError when no backend answers.
    Each backend gets timeout_seconds, all of them together total_timeout_seconds. allow_actions offers the input tools
    (the caller checks assistant.json allow_actions and the player's consent for this request)."""
    if cancel is not None and cancel.is_set():
        raise backendmod.Cancelled()
    tier = tier if tier in (1, 2, 3) else config['tier_default']
    shots = config.get('allow_screenshot') if allow_screenshot is None else allow_screenshot
    shots = bool(shots) and bool(Harness.game_pid())   # a screenshot needs the running game
    t0 = time.monotonic()
    deadline = t0 + config['total_timeout_seconds']
    # Nothing is read ahead (prefetch_state is a legacy key): the model picks its observations through the tools.
    prompt = user_prompt(tier, question, previous, shots, allow_actions)
    prompt += '\n本次当前画面：' + ('已附带游戏窗口截图。先看画面，再回答；存档只作为历史背景。' if scene_image else '不可用。不能假装看到了当前场景，不能把存档当作实时状态。')
    attempts = []
    for name in backendmod.order(backend, config):
        if cancel is not None and cancel.is_set():
            raise backendmod.Cancelled()
        remaining = deadline - time.monotonic()
        if remaining < 5:
            attempts.append(f'{name}: no time left of {config["total_timeout_seconds"]} s')
            break
        b = backendmod.make(name, config)
        ok, why = b.available()
        if not ok:
            attempts.append(f'{name}: {why}')
            continue
        if progress:
            progress(name)
        ctx = backendmod.Context(config, shots, romfs, save_root, cancel, min(config['timeout_seconds'], remaining),
                                 allow_actions)
        ctx.scene_image = scene_image
        try:
            answer = b.run(SYSTEM, prompt, ctx)
        except backendmod.BackendError as e:
            attempts.append(f'{name}: {e}')
            continue
        text = clean(answer['text'])
        if not text:
            attempts.append(f'{name}: empty answer')
            continue
        return {'text': text, 'tier': tier, 'backend': name, 'model': answer.get('model'),
                'seconds': round(time.monotonic() - t0, 1), 'attempts': attempts, 'raw': answer['text'],
                'turns': answer.get('turns'), 'cost_usd': answer.get('cost_usd')}
    raise backendmod.BackendError('没有可用的模型后端：' + '；'.join(attempts) if attempts else '没有配置模型后端')


def _write(path, value):
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def _alive(pid):
    if not pid:
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


class Service:
    def __init__(self, config, folder=None, romfs=None, save_root=None, log=print):
        self.config = config
        self.folder = Path(folder) if folder else DATA_DIR
        self.romfs, self.save_root, self.log = romfs, save_root, log
        self.sessions = {}   # session id -> bounded completed question/answer turns
        self.current = None  # (request id, cancel event, thread)
        self.lock = threading.Lock()
        self.voice = voicemod.VoiceService(self.folder, config, log)

    def respond(self, request, status, **fields):
        value = {'id': request.get('id'), 'session': request.get('session'), 'status': status, 'time': time.time()}
        value.update(fields)
        with self.lock:
            if self.current and self.current[0] != request.get('id'):
                return   # a newer request took over: drop this late answer
            _write(self.folder / RESPONSE, value)

    def work(self, request, cancel):
        tier = request.get('tier') if request.get('tier') in (1, 2, 3) else self.config['tier_default']
        session = request.get('session') or request.get('id')
        question = request.get('question')
        question = question.strip()[:MAX_QUESTION_CHARS] if isinstance(question, str) else ''
        with self.lock:
            history = list(self.sessions.get(session, []))
        # Typed follow-ups retain the conversation, including replies at the same tier.
        # The original tier buttons still reveal only earlier, less detailed hints.
        previous = history if question else [(p['tier'], p['answer']) for p in history if p['tier'] < tier]
        # Input tools only when assistant.json allows them and the player allowed this question in the panel.
        actions = bool(self.config.get('allow_actions')) and request.get('actions') is True and bool(question)
        limit = self.config['total_timeout_seconds']
        self.respond(request, 'working', tier=tier, text='正在思考……', next_tier=None, limit=limit)

        def progress(name):
            title = backendmod.make(name, self.config).title
            self.respond(request, 'working', tier=tier, backend=name, text=f'正在思考（{title}）……', next_tier=None,
                         limit=limit)
        t0 = time.monotonic()
        scene_image = None
        candidate = request.get('scene_image')
        if self.config.get('observe_current_scene') and candidate == str(self.folder / 'hint-scene.png'):
            path = Path(candidate)
            if path.is_file() and 0 <= time.time() - path.stat().st_mtime <= 15:
                scene_image = path
        try:
            result = hint(self.config, tier, request.get('backend') or 'auto', question or None, previous,
                          request.get('screenshot'), self.romfs, self.save_root, cancel, progress, scene_image=scene_image,
                          allow_actions=actions)
        except backendmod.Cancelled:
            self.log(f'[hint] request {request.get("id")} cancelled')
            self.respond(request, 'cancelled', tier=tier, text='', next_tier=None)
            return
        except Exception as e:   # the panel says what went wrong instead of waiting forever
            self.log(f'[hint] request {request.get("id")} failed: {e}')
            self.respond(request, 'error', tier=tier, text=f'这次没能给出提示：{e}'[:300], seconds=round(time.monotonic() - t0, 1),
                         next_tier=None)
            return
        if cancel.is_set():
            self.respond(request, 'cancelled', tier=tier, text='', next_tier=None)
            return
        with self.lock:
            if cancel.is_set() or (self.current and self.current[0] != request.get('id')):
                return
            turns = self.sessions.pop(session, [])
            turns.append({'tier': tier, 'question': question, 'answer': result['text']})
            self.sessions[session] = turns[-MAX_HISTORY_TURNS:]
            while len(self.sessions) > MAX_SESSIONS:
                del self.sessions[next(iter(self.sessions))]
        self.log(f'[hint] request {request.get("id")} tier {tier} by {result["backend"]} in {result["seconds"]} s'
                 + (f' (skipped: {"; ".join(result["attempts"])})' if result['attempts'] else ''))
        self.respond(request, 'done', tier=tier, text=result['text'], backend=result['backend'],
                     seconds=result['seconds'], next_tier=tier + 1 if tier < 3 else None,
                     tier_name=TIER_NAMES[tier])

    def handle(self, request):
        if not isinstance(request.get('id'), (str, int)) or not isinstance(request.get('session', request['id']), (str, int)):
            self.log('[hint] ignoring request with invalid id/session')
            return
        if request.get('cancel'):
            with self.lock:
                if self.current and self.current[0] == request.get('id'):
                    self.current[1].set()
            return
        with self.lock:
            if self.current and self.current[2].is_alive():
                self.current[1].set()   # the player asked again: the old run stops
            cancel = threading.Event()
            thread = threading.Thread(target=self.work, args=(request, cancel), daemon=True)
            self.current = (request.get('id'), cancel, thread)
        thread.start()

    def run(self, parent_pid=None, poll=0.3, accept_pending=False):
        self.folder.mkdir(parents=True, exist_ok=True)
        with open(self.folder / 'hint-serve.lock', 'w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.log('[hint] another hint service is already running; exiting')
                return 1
            path = self.folder / REQUEST
            seen, stamp = None, None
            try:   # a request left from before this service started is not answered
                old = json.loads(path.read_text(encoding='utf-8'))
                seen = old.get('id') if isinstance(old, dict) else None
                stamp = path.stat().st_mtime_ns
            except (OSError, ValueError):
                pass
            if accept_pending:
                seen, stamp = None, None
            voice_path = self.folder / voicemod.REQUEST
            try:   # 朗读 requests are never pending across a restart: the panel asks again
                voice_stamp = voice_path.stat().st_mtime_ns
            except OSError:
                voice_stamp = None
            self.log(f'[hint] service ready (requests: {path}; parent pid {parent_pid or "-"})')
            last_check = 0
            try:
                while True:
                    now = time.monotonic()
                    if parent_pid and now - last_check > 2:
                        last_check = now
                        if not _alive(parent_pid):
                            self.log('[hint] the game has exited; the hint service stops')
                            if self.current:
                                self.current[1].set()
                                self.current[2].join(timeout=8)  # let the worker reap its backend process group
                            return 0
                    request, stamp = self._changed(path, stamp)
                    if isinstance(request, dict) and (request.get('id') != seen or request.get('cancel')):
                        seen = request.get('id')
                        self.log(f'[hint] request {json.dumps(request, ensure_ascii=False)}')
                        self.handle(request)
                    request, voice_stamp = self._changed(voice_path, voice_stamp)
                    if isinstance(request, dict):
                        self.voice.handle(request)
                    self.voice.poll()
                    time.sleep(poll)
            finally:
                self.voice.close()

    @staticmethod
    def _changed(path, stamp):
        """(the request in path if it changed since stamp, else None; the new stamp)."""
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            return None, stamp
        if mtime == stamp:
            return None, stamp
        try:
            return json.loads(path.read_text(encoding='utf-8')), mtime
        except (OSError, ValueError):
            return None, None   # written half-way: the next poll sees the whole file


def serve(args):
    config = configmod.load(args.config)
    log_file = open(args.log, 'a', buffering=1, encoding='utf-8') if args.log else None

    def log(text):
        line = time.strftime('%Y-%m-%d %H:%M:%S ') + text
        print(line, file=log_file or sys.stderr, flush=True)
    try:
        return Service(config, args.folder, args.romfs, args.save_root, log).run(args.parent_pid, accept_pending=args.accept_pending)
    finally:
        if log_file:
            log_file.close()

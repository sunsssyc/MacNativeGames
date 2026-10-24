"""朗读 (optional): the panel's answer read aloud by Qwen3-TTS 0.6B Base (4-bit MLX), cloning a reference voice.

Off by default (assistant.json "voice": {"enabled": false}). Nothing is installed until the player asks for it in the
panel (or `run.py voice install`); until then, and whenever this voice cannot answer, the game reads with the macOS
system voice. Everything lives in the game's data folder, under tts/:

    venv/                 a Python environment with mlx-audio, made from this service's own Python
    hf/                   the model (Hugging Face cache)
    reference.wav + .txt  the voice to clone and what it says: the player's own recording, or a friend's who agreed.
                          The Base model has no voice of its own (without a reference it does not stop: "你好" ran to
                          655 s of audio in testing), so until there is a reference the game reads with the system voice.

The game (runtime/hint_voice.inc) writes hint-voice-request.json. Reading answers in hint-voice.json:
    {"id": "...", "pages": ["...", "..."]}  ->  {"id": "...", "status": "working"|"done", "files": ["/…/0.wav", null]}
    {"id": "...", "cancel": true}               the panel was closed or reading was switched off
    {"id": "...", "warm": true}             load the model while the answer is being worked out (no reply)
    status "missing": not installed (or being installed); "no_reference": no voice to clone yet; "error": with "text".
Setting up answers in hint-voice-setup.json, so a page being read never hides an install's progress:
    {"id": "...", "install": true}          ->  {"id": "...", "status": "installing", "text": "..."} ... "installed"
    {"id": "...", "reference": "/…/take.caf", "text": "..."}  ->  "reference_saved" (the panel's 录我的声音)
    Pages are synthesized in order, while the game is paused
    behind the panel (the model shares the GPU with the game), and the worker is stopped after idle seconds."""
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from .romfs import DATA_DIR

MODEL = 'mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit'
PACKAGE = 'mlx-audio==0.6.1'
WORKER = Path(__file__).resolve().with_name('tts_worker.py')
REQUEST = 'hint-voice-request.json'
RESPONSE = 'hint-voice.json'
SETUP = 'hint-voice-setup.json'
MAX_PAGES = 4
MAX_PAGE_CHARS = 160


def _write(path, value):
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


class VoiceError(Exception):
    pass


class Voice:
    def __init__(self, folder=None, config=None, log=print):
        self.folder = Path(folder) if folder else DATA_DIR
        self.root = self.folder / 'tts'
        self.config = (config or {}).get('voice') or {}
        self.log = log
        self.worker = None
        self.used = 0.0
        self.lock = threading.Lock()   # one page at a time through the worker

    # installation -----------------------------------------------------------------------------------------------------
    @property
    def python(self):
        return self.root / 'venv/bin/python'

    def env(self):
        env = dict(os.environ, HF_HOME=str(self.root / 'hf'), HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false')
        env.pop('PYTHONPATH', None)
        return env

    def model_path(self):
        """The downloaded model folder, or None."""
        snapshots = self.root / 'hf/hub' / f'models--{MODEL.replace("/", "--")}' / 'snapshots'
        for folder in sorted(snapshots.glob('*'), reverse=True) if snapshots.is_dir() else ():
            weights = list(folder.glob('**/*.safetensors'))
            if (folder / 'config.json').is_file() and len(weights) >= 2 and all(w.is_file() for w in weights):
                return folder
        return None

    def installed(self):
        return self.python.is_file() and self.model_path() is not None

    def install(self, progress=lambda text: None, cancel=None):
        """venv + mlx-audio + model; each step is skipped when done, so an interrupted install resumes."""
        self.root.mkdir(parents=True, exist_ok=True)
        steps = []
        if not self.python.is_file():
            steps.append(('正在准备语音环境……', [sys.executable, '-m', 'venv', str(self.root / 'venv')]))
        if not self.python.is_file() or subprocess.run([str(self.python), '-I', '-c', 'import mlx_audio'],
                                                      capture_output=True, env=self.env()).returncode:
            steps.append(('正在安装 mlx-audio（约 450 MB）……',
                          [str(self.python), '-m', 'pip', 'install', '-q', '--disable-pip-version-check', PACKAGE]))
        if self.model_path() is None:
            fetch = ('from huggingface_hub import snapshot_download; '
                     f'print(snapshot_download({MODEL!r}))')
            # Plain HTTP: the Xet transfer stalled on the 1 GB weights file in testing; HTTP resumes a partial download.
            steps.append(('正在下载 Qwen3-TTS 0.6B 4bit（约 1.7 GB）……', [str(self.python), '-I', '-c', fetch]))
        for text, command in steps:
            if cancel is not None and cancel.is_set():
                raise VoiceError('安装已取消')
            progress(text)
            env = dict(self.env(), HF_HUB_DISABLE_XET='1')
            done = subprocess.run(command, capture_output=True, text=True, env=env)
            if done.returncode:
                detail = (done.stderr.strip().splitlines() or done.stdout.strip().splitlines() or [''])[-1]
                raise VoiceError(f'{text.rstrip("……")}失败：{detail[:200]}')
        if not self.installed():
            raise VoiceError('语音模型没有下载完整')

    # the worker -------------------------------------------------------------------------------------------------------
    def _read(self, timeout):
        """The worker's next JSON line within timeout seconds (other lines are the libraries' own prints)."""
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            try:
                line = self.lines.get(timeout=left)
            except queue.Empty:
                break
            if line is None:   # the worker exited
                break
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
        self.stop()
        raise VoiceError('语音模型没有响应')

    def _start(self):
        if self.worker and self.worker.poll() is None:
            return
        model = self.model_path()
        if not model or not self.python.is_file():
            raise VoiceError('语音模型尚未安装')
        log = open(self.root / 'worker.log', 'a', encoding='utf-8')
        self.worker = subprocess.Popen([str(self.python), '-I', str(WORKER), str(model)], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=log, text=True, env=dict(self.env(), HF_HUB_OFFLINE='1'),
                                       start_new_session=True)
        log.close()
        self.lines = queue.Queue()
        # A thread drains standard output line by line: waiting on the pipe itself misses a line that the
        # library's own print left in the same buffered read.
        def drain(out, lines):
            for line in out:
                lines.put(line)
            lines.put(None)
        threading.Thread(target=drain, args=(self.worker.stdout, self.lines), daemon=True).start()
        ready = self._read(180)
        if not ready.get('ready'):
            self.stop()
            raise VoiceError('语音模型没有启动')
        self.log(f'[voice] model loaded ({model.name[:8]})')

    def stop(self):
        worker, self.worker = self.worker, None
        if worker and worker.poll() is None:
            try:
                worker.stdin.close()
                worker.wait(3)
            except (OSError, subprocess.TimeoutExpired):
                worker.kill()
                worker.wait()

    def idle(self):
        """Free the model's memory once reading has been idle for voice.unload_after_seconds (default 120)."""
        limit = self.config.get('unload_after_seconds', 120)
        if self.worker and not self.lock.locked() and time.monotonic() - self.used > limit:
            self.log('[voice] idle: model unloaded')
            self.stop()

    def synthesize(self, text, out, reference=None, seed=None):
        """Write out (WAV); (seconds taken, seconds of audio)."""
        with self.lock:
            self._start()
            request = {'text': text, 'out': str(out), 'seed': seed}
            if reference:
                request['ref_audio'], request['ref_text'] = str(reference[0]), reference[1]
            self.worker.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
            self.worker.stdin.flush()
            reply = self._read(max(60, 2 * len(text)))
            self.used = time.monotonic()
        if not reply.get('ok'):
            raise VoiceError(reply.get('error') or '朗读失败')
        return reply.get('seconds'), reply.get('audio_seconds')

    def reference(self):
        """(wav, its text) of the voice to clone, or None."""
        wav, txt = self.root / 'reference.wav', self.root / 'reference.txt'
        if wav.is_file() and txt.is_file():
            text = txt.read_text(encoding='utf-8').strip()
            if text:
                return wav, text
        return None

    def set_reference(self, audio, text):
        """Use a recording as the voice: converted to 24 kHz mono WAV (afconvert), its words in reference.txt."""
        text = (text or '').strip()
        if not text:
            raise VoiceError('需要参考录音里说的原话')
        self.root.mkdir(parents=True, exist_ok=True)
        out = self.root / 'reference.wav'
        done = subprocess.run(['/usr/bin/afconvert', '-f', 'WAVE', '-d', 'LEI16@24000', '-c', '1', str(audio),
                               str(out)], capture_output=True, text=True)
        if done.returncode:
            raise VoiceError(f'录音无法转换：{(done.stderr.strip() or "afconvert failed")[:200]}')
        (self.root / 'reference.txt').write_text(text, encoding='utf-8')
        return out


def pages_of(value):
    pages = value.get('pages') if isinstance(value, dict) else None
    if not isinstance(pages, list) or not pages or len(pages) > MAX_PAGES:
        return None
    if not all(isinstance(p, str) and 0 < len(p.strip()) <= MAX_PAGE_CHARS for p in pages):
        return None
    return [p.strip() for p in pages]


class VoiceService:
    """The hint service's side of 朗读: one reading job at a time (a new request or a cancel stops the current one),
    and one setup job (install or a new reference) that reading requests never interrupt."""

    def __init__(self, folder, config, log):
        self.voice = Voice(folder, config, log)
        self.folder = self.voice.folder
        self.log = log
        self.current = None   # (id, cancel event, thread) of the reading job
        self.setup = None     # the setup thread
        self.lock = threading.Lock()

    def respond(self, request_id, status, **fields):
        with self.lock:
            if not self.current or self.current[0] != request_id or self.current[1].is_set():
                return   # superseded or cancelled: a page that was already being made is dropped
            _write(self.folder / RESPONSE, dict({'id': request_id, 'status': status, 'time': time.time()}, **fields))

    def respond_setup(self, request_id, status, **fields):
        _write(self.folder / SETUP, dict({'id': request_id, 'status': status, 'time': time.time()}, **fields))

    def installing(self):
        return self.setup is not None and self.setup.is_alive()

    def handle(self, request):
        request_id = request.get('id')
        if not isinstance(request_id, str):
            return
        if request.get('install') or request.get('reference'):
            if self.installing():
                self.respond_setup(request_id, 'error', text='语音正在安装，请稍候')
                return
            target = self.install if request.get('install') else self.save
            self.setup = threading.Thread(target=target, args=(request,), daemon=True)
            self.setup.start()
            return
        with self.lock:
            if self.current:
                self.current[1].set()
            if request.get('cancel'):
                self.current = None
                return
            cancel = threading.Event()
            target = self.warm if request.get('warm') else self.speak
            thread = threading.Thread(target=target, args=(request, cancel), daemon=True)
            self.current = (request_id, cancel, thread)
        thread.start()

    def install(self, request):
        request_id = request['id']
        try:
            self.voice.install(lambda text: self.respond_setup(request_id, 'installing', text=text))
        except VoiceError as e:
            self.log(f'[voice] install failed: {e}')
            self.respond_setup(request_id, 'error', text=str(e))
            return
        self.log('[voice] installed')
        self.respond_setup(request_id, 'installed', text='语音已安装', reference=self.voice.reference() is not None)

    def warm(self, request, cancel):
        """Load the model and encode the reference once, so the first page does not wait for either."""
        reference = self.voice.reference()
        if self.installing() or not self.voice.installed() or reference is None:
            return
        try:
            self.voice.synthesize('嗯。', self.voice.root / 'warm.wav', reference)
        except VoiceError as e:
            self.log(f'[voice] warm-up failed: {e}')

    def save(self, request):
        try:
            self.voice.set_reference(request['reference'], request.get('text'))
        except (VoiceError, OSError) as e:
            self.respond_setup(request['id'], 'error', text=str(e))
            return
        self.log('[voice] reference voice saved')
        self.respond_setup(request['id'], 'reference_saved', text='已保存你的声音', installed=self.voice.installed())

    def speak(self, request, cancel):
        request_id, pages = request['id'], pages_of(request)
        if pages is None:
            self.respond(request_id, 'error', text='朗读请求无效')
            return
        if self.installing() or not self.voice.installed():
            self.respond(request_id, 'missing', text='语音正在安装' if self.installing() else '语音模型尚未安装')
            return
        reference = self.voice.reference()
        if reference is None:
            self.respond(request_id, 'no_reference', text='还没有录参考声音')
            return
        out = self.folder / 'hint-audio'
        if out.is_dir():
            shutil.rmtree(out, ignore_errors=True)   # last answer's pages
        out.mkdir(parents=True, exist_ok=True)
        files = [None] * len(pages)
        try:
            self.respond(request_id, 'working', files=files)
            for i, page in enumerate(pages):
                if cancel.is_set():
                    return
                path = out / f'{request_id[:12]}-{i}.wav'
                took, length = self.voice.synthesize(page, path, reference)
                files[i] = str(path)
                self.log(f'[voice] page {i + 1}/{len(pages)}: {length} s of audio in {took} s')
                self.respond(request_id, 'working' if i + 1 < len(pages) else 'done', files=files)
        except VoiceError as e:
            self.log(f'[voice] failed: {e}')
            self.respond(request_id, 'error', text=str(e), files=files)

    def poll(self):
        self.voice.idle()

    def close(self):
        if self.current:
            self.current[1].set()
        self.voice.stop()

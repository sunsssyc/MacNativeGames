"""朗读 (optional): the panel's answer read aloud, line by line as it is written.

Off by default (assistant.json "voice": {"enabled": false}). Three voices, chosen per answer by voice.engine ("auto"):
    local    Qwen3-TTS 0.6B Base (4-bit MLX) cloning a recorded reference voice; used once it is installed and a
             reference recorded (the panel's 下载语音 / 录我的声音 when voice.engine is "local", or `run.py voice`).
             It shares the GPU with the game, so it reads only behind the open panel, while the game is paused.
    google   Chirp 3 HD on Google Cloud Text-to-Speech with the gcloud sign-in of the Vertex backend: 1 million
             characters a month free, then billed; voice.google_monthly_chars (900,000) stops it short of that.
    (none)   the game reads with the macOS system voice ("system" below): no service, nothing downloaded.

The local voice lives in the game's data folder, under tts/:
    venv/                 a Python environment with mlx-audio, made from this service's own Python
    hf/                   the model (Hugging Face cache)
    reference.wav + .txt  the voice to clone and what it says: the player's own recording, or a friend's who agreed.
                          The Base model has no voice of its own (without a reference it does not stop: "你好" ran to
                          655 s of audio in testing).

Reading: a hint request with "read": true is read while it streams (Service.work feeds the job), and the game writes
hint-voice-request.json for an answer already on screen. Replies in hint-voice.json, one file per line of the answer:
    {"id": "...", "lines": ["...", "..."]}  ->  {"id": "...", "status": "working"|"done", "engine": "google",
                                                 "files": ["/…/0.wav", "/…/1.wav"]}
    {"id": "...", "cancel": true}               the panel was closed (local voice) or reading was switched off
    status "system": no voice here (or it failed, "text" says why): the game's system voice reads from that line on;
    "local" then says why the clone is not used: "missing", "no_reference", "installing" or "ready".
Setting up the local voice answers in hint-voice-setup.json, so a line being read never hides an install's progress:
    {"id": "...", "install": true}          ->  {"id": "...", "status": "installing", "text": "..."} ... "installed"
    {"id": "...", "reference": "/…/take.caf", "text": "..."}  ->  "reference_saved" (the panel's 录我的声音)
The local model is unloaded after voice.unload_after_seconds idle."""
import base64
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .romfs import DATA_DIR

MODEL = 'mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit'
PACKAGE = 'mlx-audio==0.6.1'
WORKER = Path(__file__).resolve().with_name('tts_worker.py')
REQUEST = 'hint-voice-request.json'
RESPONSE = 'hint-voice.json'
SETUP = 'hint-voice-setup.json'
MAX_LINES = 12
MAX_LINE_CHARS = 120
GOOGLE_URL = 'https://texttospeech.googleapis.com/v1/text:synthesize'
GOOGLE_VOICE = 'cmn-CN-Chirp3-HD-Leda'   # "youthful"; any cmn-CN Chirp 3 HD voice in voice.google_voice
SENTENCE_ENDS = '。！？!?…'


def _write(path, value):
    tmp = path.with_name(f'.{path.name}.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


class VoiceError(Exception):
    pass


class Voice:
    """The local voice: Qwen3-TTS through a worker process in its own Python environment."""
    name = 'local'

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

    def ready(self):
        return self.installed() and self.reference() is not None

    def prepare(self):
        """Load the model and encode the reference once, so the first line does not wait for either."""
        self.synthesize('嗯。', self.root / 'warm.wav', self.reference())

    def speak(self, text, out):
        self.synthesize(text, out, self.reference())

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


class GoogleVoice:
    """Chirp 3 HD on Google Cloud Text-to-Speech, signed in like the Vertex backend (gcloud). Characters are counted per
    month in tts/google-usage.json and the voice stops at voice.google_monthly_chars, short of the paid range."""
    name = 'google'

    def __init__(self, folder, config, log=print):
        self.config = config
        self.settings = config.get('voice') or {}
        self.usage = Path(folder) / 'tts' / 'google-usage.json'
        self.log = log

    def used(self):
        try:
            return int(json.loads(self.usage.read_text()).get(time.strftime('%Y-%m'), 0))
        except (OSError, ValueError, AttributeError):
            return 0

    def left(self):
        return self.settings.get('google_monthly_chars', 900_000) - self.used()

    def ready(self):
        from .vertex import VertexREST
        return VertexREST(self.config).available()[0] and self.left() > 0

    def prepare(self):
        self._token()   # the sign-in, cached for 40 minutes

    def _token(self):
        from .backends import BackendError
        from .vertex import VertexREST
        try:
            return VertexREST(self.config).token()
        except BackendError as e:
            raise VoiceError(str(e)) from None

    def speak(self, text, out):
        if len(text) > self.left():
            raise VoiceError('本月 Google 朗读额度已用完')
        from .vertex import project_and_region
        project, _ = project_and_region(self.config)
        body = {'input': {'text': text},
                'voice': {'languageCode': 'cmn-CN', 'name': self.settings.get('google_voice') or GOOGLE_VOICE},
                'audioConfig': {'audioEncoding': 'LINEAR16', 'sampleRateHertz': 24000}}
        request = urllib.request.Request(GOOGLE_URL, data=json.dumps(body, ensure_ascii=False).encode(), headers={
            'Authorization': f'Bearer {self._token()}', 'x-goog-user-project': project,
            'Content-Type': 'application/json; charset=utf-8'})
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                audio = base64.b64decode(json.load(response)['audioContent'])   # a WAV file, header included
        except urllib.error.HTTPError as e:
            raise VoiceError(f'Google 朗读失败：HTTP {e.code}') from None
        except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
            raise VoiceError(f'Google 朗读失败：{e}') from None
        tmp = Path(f'{out}.part')
        tmp.write_bytes(audio)
        tmp.replace(out)
        counts = {}
        try:
            counts = json.loads(self.usage.read_text())
        except (OSError, ValueError):
            pass
        month = time.strftime('%Y-%m')
        counts = {month: int(counts.get(month, 0)) + len(text)}   # only this month is kept
        self.usage.parent.mkdir(parents=True, exist_ok=True)
        _write(self.usage, counts)


def lines_of(text):
    return [line.strip() for line in (text or '').split('\n') if line.strip()]


def finished_lines(text, final):
    """The lines of an answer being written that are finished: all once final, else all but the last unless the last
    already ends a sentence."""
    lines = lines_of(text)
    if not final and lines and not lines[-1].endswith(tuple(SENTENCE_ENDS)):
        lines = lines[:-1]
    return lines


def request_lines(value):
    lines = value.get('lines') if isinstance(value, dict) else None
    if not isinstance(lines, list) or not lines or len(lines) > MAX_LINES:
        return None
    if not all(isinstance(line, str) and 0 < len(line.strip()) <= MAX_LINE_CHARS for line in lines):
        return None
    return [line.strip() for line in lines]


class Job:
    """One answer being read: its lines so far, more to come until final."""

    def __init__(self, job_id, lines=(), final=True):
        self.id = job_id
        self.lines = list(lines)
        self.final = final
        self.cancel = threading.Event()
        self.wake = threading.Condition()


class VoiceService:
    """The hint service's side of 朗读: one reading job at a time (a new one or a cancel stops it), and one setup job
    (install or a new reference) that reading never interrupts."""

    def __init__(self, folder, config, log):
        self.voice = Voice(folder, config, log)
        self.google = GoogleVoice(self.voice.folder, config, log)
        self.settings = config.get('voice') or {}
        self.folder = self.voice.folder
        self.log = log
        self.job = None
        self.setup = None
        self.lock = threading.Lock()

    def installing(self):
        return self.setup is not None and self.setup.is_alive()

    def local(self):
        """The local clone's state, for the panel's 下载语音 / 录我的声音."""
        if self.installing():
            return 'installing'
        return 'missing' if not self.voice.installed() else 'no_reference' if self.voice.reference() is None else 'ready'

    def engine(self):
        """The voice for a new answer: the cloned one once it is set up, else Google, else None (the system voice)."""
        choice = self.settings.get('engine', 'auto')
        if choice in ('auto', 'local') and not self.installing() and self.voice.ready():
            return self.voice
        if choice in ('auto', 'google') and self.google.ready():
            return self.google
        return None

    def respond(self, job, status, **fields):
        with self.lock:
            if self.job is not job or job.cancel.is_set():
                return   # superseded or cancelled: a line that was already being made is dropped
            _write(self.folder / RESPONSE, dict({'id': job.id, 'status': status, 'time': time.time()}, **fields))

    def respond_setup(self, request_id, status, **fields):
        _write(self.folder / SETUP, dict({'id': request_id, 'status': status, 'time': time.time()}, **fields))

    # reading ------------------------------------------------------------------------------------------------------------
    def stop(self, job_id=None):
        with self.lock:
            job = self.job
            if job and (job_id is None or job.id == job_id):
                job.cancel.set()
                self.job = None
        if job:
            with job.wake:
                job.wake.notify_all()

    def start(self, job_id, lines=(), final=True):
        """Read lines (more follow through feed until final); the job before stops."""
        self.stop()
        job = Job(str(job_id), lines, final)
        with self.lock:
            self.job = job
        threading.Thread(target=self.read, args=(job,), daemon=True).start()
        return job

    def feed(self, job_id, text, final=False):
        """The streaming answer of a reading job: its finished lines so far."""
        with self.lock:
            job = self.job
        if not job or job.id != str(job_id):
            return
        with job.wake:
            job.lines = finished_lines(text, final)
            job.final = final
            job.wake.notify_all()

    def read(self, job):
        engine = self.engine()
        if engine is None:
            self.respond(job, 'system', text='没有可用的朗读声音', local=self.local())
            return
        out = self.folder / 'hint-audio'
        shutil.rmtree(out, ignore_errors=True)   # the answer before this one
        out.mkdir(parents=True, exist_ok=True)
        files, spoken = [], []   # spoken: the text of each file, to notice a line rewritten while streaming
        try:
            engine.prepare()
            while True:
                with job.wake:
                    while not job.cancel.is_set():
                        same = next((k for k, text in enumerate(spoken) if k >= len(job.lines) or job.lines[k] != text),
                                    len(spoken))
                        del files[same:], spoken[same:]   # lines that changed are made again
                        if len(spoken) < len(job.lines) or job.final:
                            break
                        job.wake.wait(0.5)
                    if job.cancel.is_set():
                        return
                    if len(spoken) >= len(job.lines):
                        break
                    i, line = len(spoken), job.lines[len(spoken)]
                path = out / f'{job.id[:12]}-{i}-{time.monotonic_ns() % 10**9}.wav'
                engine.speak(line, path)
                files.append(str(path))
                spoken.append(line)
                self.respond(job, 'working', engine=engine.name, files=files)
        except VoiceError as e:
            self.log(f'[voice] {engine.name}: {e}')
            self.respond(job, 'system', engine=engine.name, files=files, text=str(e), local=self.local())
            return
        self.respond(job, 'done', engine=engine.name, files=files)

    # setup --------------------------------------------------------------------------------------------------------------
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
        if request.get('cancel'):
            self.stop(request_id)
            return
        lines = request_lines(request)
        if lines is None:
            return
        self.start(request_id, lines, final=True)

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

    def save(self, request):
        try:
            self.voice.set_reference(request['reference'], request.get('text'))
        except (VoiceError, OSError) as e:
            self.respond_setup(request['id'], 'error', text=str(e))
            return
        self.log('[voice] reference voice saved')
        self.respond_setup(request['id'], 'reference_saved', text='已保存你的声音', installed=self.voice.installed())

    def poll(self):
        self.voice.idle()

    def close(self):
        self.stop()
        self.voice.stop()

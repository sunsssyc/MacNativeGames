"""Same bounded runtime operations for CLI and MCP; no shell commands or screenshots.

The game (runtime/hint_runtime_tools.inc) answers runtime-request.json with runtime-response.json. It takes a press only
while the player's current request is allowed to act (the panel's 「允许操作」), a few per request; otherwise the reply
is {"ok": false, "error": "actions_not_allowed"}."""
import fcntl
import json
import os
import time
import uuid
from pathlib import Path

from .romfs import DATA_DIR

BUTTONS = ('a', 'b', 'x', 'y', 'l', 'r', 'zl', 'zr', 'plus', 'minus', 'up', 'down', 'left', 'right', 'forward', 'backward',
           'strafe_left', 'strafe_right', 'look_left', 'look_right', 'look_up', 'look_down')


def _ms(value, low, high):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and low <= value <= high


def call(op='state', button=None, duration_ms=150, folder=None):
    if op not in ('state', 'press', 'stop', 'wait'):
        raise ValueError('unknown operation')
    if op == 'press' and (button not in BUTTONS or not _ms(duration_ms, 30, 1000)):
        raise ValueError('press requires a known button and 30..1000 ms')
    if op == 'wait':
        if not _ms(duration_ms, 0, 1000):
            raise ValueError('wait requires 0..1000 ms')
        time.sleep(duration_ms / 1000)
        op = 'state'
    root = Path(folder) if folder else DATA_DIR
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'runtime-client.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        request = {'id': uuid.uuid4().hex, 'op': op, 'time': time.time(), 'button': button, 'duration_ms': duration_ms}
        tmp = root / f'.runtime-{os.getpid()}.tmp'
        tmp.write_text(json.dumps(request))
        tmp.replace(root / 'runtime-request.json')
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            try:
                reply = json.loads((root / 'runtime-response.json').read_text())
                if reply.get('id') == request['id']:
                    return reply
            except (OSError, ValueError):
                pass
            time.sleep(.05)
        raise TimeoutError('runtime did not respond; no save-data fallback was used')

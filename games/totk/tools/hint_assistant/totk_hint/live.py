"""Same bounded runtime operations for CLI and MCP; no shell commands or screenshots.

The game (runtime/hint_runtime_tools.inc) answers runtime-request.json with runtime-response.json. It takes a press
only while the player's current request is allowed to act (the panel's 「允许操作」), a few per request (assistant.json
action_limit); otherwise the reply is {"ok": false, "error": "actions_not_allowed"}. "sequence" sends a short run of
presses in one call, so a few steps need one model turn instead of one each; every step still counts against the same
budget and the game stops the run on Esc or when the panel closes."""
import fcntl
import json
import os
import time
import uuid
from pathlib import Path

from .romfs import DATA_DIR

BUTTONS = ('a', 'b', 'x', 'y', 'l', 'r', 'zl', 'zr', 'plus', 'minus', 'up', 'down', 'left', 'right', 'forward', 'backward',
           'strafe_left', 'strafe_right', 'look_left', 'look_right', 'look_up', 'look_down')
MAX_STEPS = 8
DEFAULT_STEP_MS = 150
DEFAULT_WAIT_MS = 150


def _ms(value, low, high):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and low <= value <= high


def checked_steps(value):
    """Validated sequence steps: [{"button", "duration_ms", "wait_ms"}], at most MAX_STEPS."""
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_STEPS:
        raise ValueError(f'sequence needs 1 to {MAX_STEPS} steps')
    out = []
    for step in value:
        if not isinstance(step, dict):
            raise ValueError('each sequence step must be an object')
        button = step.get('button')
        duration = step.get('duration_ms', DEFAULT_STEP_MS)
        wait = step.get('wait_ms', DEFAULT_WAIT_MS)
        if button not in BUTTONS:
            raise ValueError(f'unknown button {button!r}')
        if not _ms(duration, 30, 1000) or not _ms(wait, 0, 1000):
            raise ValueError('a step is 30..1000 ms with a 0..1000 ms wait')
        out.append({'button': button, 'duration_ms': duration, 'wait_ms': wait})
    return out


def call(op='state', button=None, duration_ms=150, steps=None, folder=None):
    if op not in ('state', 'press', 'stop', 'wait', 'sequence'):
        raise ValueError('unknown operation')
    if op == 'press' and (button not in BUTTONS or not _ms(duration_ms, 30, 1000)):
        raise ValueError('press requires a known button and 30..1000 ms')
    if op == 'sequence':
        steps = checked_steps(steps)
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
        if op == 'sequence':
            request['steps'] = steps
        tmp = root / f'.runtime-{os.getpid()}.tmp'
        tmp.write_text(json.dumps(request))
        tmp.replace(root / 'runtime-request.json')
        # A single press answers after its own duration; a sequence after all of its presses and waits.
        budget = duration_ms / 1000
        if op == 'sequence':
            budget = sum(s['duration_ms'] + s['wait_ms'] for s in steps) / 1000
        deadline = time.monotonic() + min(20.0, 4.0 + budget)
        while time.monotonic() < deadline:
            try:
                reply = json.loads((root / 'runtime-response.json').read_text())
                if reply.get('id') == request['id']:
                    return reply
            except (OSError, ValueError):
                pass
            time.sleep(.05)
        raise TimeoutError('runtime did not respond; no save-data fallback was used')

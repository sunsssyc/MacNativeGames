"""The real cooperative gate blocks producers, never its UI request thread."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <time.h>
#include "settings_pause.inc"
static _Atomic int completed;
static void *producer(void *unused) {
    (void)unused;
    assert(runtime_settings_pause_checkpoint() == 1);
    atomic_fetch_add(&completed, 1);
    return 0;
}
static void delay(void) { struct timespec t = {0, 1000000}; nanosleep(&t, 0); }
int main(void) {
    assert(runtime_settings_pause_checkpoint() == 0);
    /* Repeated setter calls are idempotent, not unmatched refcounts. */
    for (int round = 0; round < 20; round++) {
        pthread_t a, b;
        atomic_store(&completed, 0);
        runtime_settings_pause(1); runtime_settings_pause(1);
        assert(!pthread_create(&a, 0, producer, 0));
        assert(!pthread_create(&b, 0, producer, 0));
        for (int i = 0; i < 1000 && atomic_load(&settings_pause_waiters) != 2; i++) delay();
        assert(runtime_settings_paused());
        assert(atomic_load(&settings_pause_waiters) == 2);
        /* A spurious wake must not release either producer. */
        pthread_mutex_lock(&settings_pause_lock);
        pthread_cond_broadcast(&settings_pause_changed);
        pthread_mutex_unlock(&settings_pause_lock);
        for (int i = 0; i < 10; i++) delay();
        assert(!atomic_load(&completed));
        runtime_settings_pause(0);
        assert(!pthread_join(a, 0)); assert(!pthread_join(b, 0));
        assert(atomic_load(&completed) == 2);
        assert(!runtime_settings_paused());
        assert(runtime_settings_pause_checkpoint() == 0);
    }
    /* Assistant and settings own independent pause reasons. */
    runtime_settings_pause(1); runtime_assistant_pause(1);
    runtime_assistant_pause(0); assert(settings_pause_requested);
    runtime_assistant_pause(1); runtime_settings_pause(0); assert(assistant_pause_requested);
    runtime_assistant_pause(0); assert(runtime_settings_pause_checkpoint() == 0);
    /* Closing before the next frame does not leave a latent pause. */
    runtime_settings_pause(1); runtime_settings_pause(0);
    assert(runtime_settings_pause_checkpoint() == 0);
    return 0;
}
'''

class SettingsPauseTests(unittest.TestCase):
    def test_cooperative_pause(self):
        cc = shutil.which('clang') or shutil.which('cc')
        if not cc:
            self.skipTest('C compiler required')
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'pause.c'
            binary = Path(tmp) / 'pause'
            source.write_text(PROBE)
            build = subprocess.run([cc, '-std=c11', '-D_POSIX_C_SOURCE=200809L',
                                    '-Wall', '-Wextra', '-Werror', '-pthread',
                                    '-I' + str(ROOT / 'games/totk/runtime'),
                                    str(source), '-o', str(binary)],
                                   capture_output=True, text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 0, run.stderr)

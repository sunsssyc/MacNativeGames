/* Cooperative settings pause. Only the frame-producing guest thread waits;
 * AppKit, the GPU replay queue, audio and I/O remain able to complete work.
 * Called at present entry, outside graphics locks and with the virtual core released.
 * This state belongs solely to settings: it never changes focus or game pause state. */
#include <pthread.h>
#include <stdatomic.h>
static pthread_mutex_t settings_pause_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t settings_pause_changed = PTHREAD_COND_INITIALIZER;
static int settings_pause_requested;
static int assistant_pause_requested;
static _Atomic int settings_pause_waiters;
void runtime_settings_pause(int on) {
    pthread_mutex_lock(&settings_pause_lock);
    settings_pause_requested = !!on;
    if (!on) pthread_cond_broadcast(&settings_pause_changed);
    pthread_mutex_unlock(&settings_pause_lock);
}
void runtime_assistant_pause(int on) {
    pthread_mutex_lock(&settings_pause_lock);
    assistant_pause_requested = !!on;
    if (!on) pthread_cond_broadcast(&settings_pause_changed);
    pthread_mutex_unlock(&settings_pause_lock);
}
int runtime_settings_paused(void) { return atomic_load(&settings_pause_waiters) != 0; }
int runtime_settings_pause_checkpoint(void) {
    int waited = 0;
    pthread_mutex_lock(&settings_pause_lock);
    if (settings_pause_requested || assistant_pause_requested) {
        waited = 1;
        atomic_fetch_add(&settings_pause_waiters, 1);
        while (settings_pause_requested || assistant_pause_requested)
            pthread_cond_wait(&settings_pause_changed, &settings_pause_lock);
        atomic_fetch_sub(&settings_pause_waiters, 1);
    }
    pthread_mutex_unlock(&settings_pause_lock);
    return waited;
}

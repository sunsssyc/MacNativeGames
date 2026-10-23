/* Exercise the actual runtime integration, using an in-memory module and GPU
   sample provider; no game image, window, or graphics device is required. */
#include "../../runtime/game_patches_v143.c"
#include <assert.h>
static uint32_t test_frame;
int nvn_gpu_frame_ms(uint32_t *frame, float *ms) { *frame = ++test_frame; *ms = 40; return 1; }
_Noreturn void runtime_fail(const char *message) { fprintf(stderr, "%s\n", message); abort(); }
static void config_tests(void) {
    struct { const char *target, *cap; float expected; } cases[] = {
        {NULL, NULL, 16.7f}, {"", "40", 25}, {"20junk", "40", 25},
        {"nan", "60", 1000.0f / 60}, {"inf", "0", 16.7f}, {"1e999", "40", 25},
        {"3.9", "40", 25}, {"100.1", "40", 25}, {"4", "40", 4}, {"100", "40", 100},
        {"20", "40", 20}, {NULL, "20", 1000.0f / 30}, {NULL, "999", 1000.0f / 240},
        {NULL, "30", 1000.0f / 30}, {NULL, "240", 1000.0f / 240},
        {"20junk", "40junk", 16.7f}, {NULL, "-1", 16.7f}, {NULL, "nan", 16.7f},
        {NULL, "inf", 16.7f}, {NULL, "1e999", 16.7f}, {NULL, "1e-999", 16.7f},
    };
    for (unsigned i = 0; i < sizeof cases / sizeof *cases; i++) {
        drs_configure(NULL, cases[i].target, cases[i].cap);
        assert(fabsf(atomic_load(&drs_target) - cases[i].expected) < 0.001f);
    }
    const char *bad_min[] = {NULL, "", "0.8junk", "nan", "inf", "1e999", "1e-999"};
    for (unsigned i = 0; i < sizeof bad_min / sizeof *bad_min; i++) {
        drs_configure(bad_min[i], NULL, NULL); assert(runtime_drs_min() == 0.67f);
    }
    drs_configure("0.8", NULL, NULL); assert(runtime_drs_min() == 0.8f);
    drs_configure("0.2", NULL, NULL); assert(runtime_drs_min() == 0.5f);
    drs_configure("2", NULL, NULL); assert(runtime_drs_min() == 1);
}
int main(void) {
    config_tests();
    /* Resuming a 150 ms settings pause must not feed that interval into the
       game step (normal long-stall rejection only starts at 250 ms). */
    _Atomic uint64_t step = 0;
    _Atomic uint32_t interval = 0;
    frame_step_data = &step; frame_interval_data = &interval;
    runtime_frame_step_update(1000000000);
    runtime_frame_step_update(1016666667);
    uint64_t before_pause = atomic_load(&step);
    assert(before_pause && frame_sample_count == 1);
    runtime_frame_step_update(0);
    runtime_frame_step_update(1166666667);
    assert(atomic_load(&step) == before_pause && frame_sample_count == 0);
    runtime_frame_step_update(1183333334);
    assert(atomic_load(&step) == before_pause && frame_sample_count == 1);
    frame_step_data = NULL; frame_interval_data = NULL;
    Module m = {.text_end = 0x58f000, .file_size = 0x600000, .size = 0x604000};
    assert(!posix_memalign((void **)&m.base, 0x4000, m.size)); memset(m.base, 0, m.size);
    uint32_t original = 0x2a1703e9; memcpy(m.base + 0x5848a8, &original, 4);
    setenv("TOTK_DRS", "1", 1); setenv("TOTK_FPS_CAP", "40", 1);
    unsetenv("TOTK_DRS_TARGET_MS"); unsetenv("TOTK_DRS_MIN"); unsetenv("TOTK_FIXED_RES");
    patch_fixed_res(&m);
    assert(runtime_drs_enabled()); assert(runtime_drs_min() == 0.67f); assert(atomic_load(&drs_target) == 25);
    uint32_t *code = (uint32_t *)(void *)(m.base + 0x58f000 + 928);
    /* Decode actual branch targets, TBZ bit index and LDR offset. */
    assert(((code[2] >> 5) & 0x3fff) * 4 == 12);
    assert(((code[2] >> 31) << 5 | ((code[2] >> 19) & 31)) == 32);
    assert(((code[1] >> 10) & 0xfff) * 8 == 48);
    assert(code[5] == original);
    runtime_drs_set_target_ms(16.7f);
    for (uint64_t i = 1; i < 200; i++) runtime_frame_step_update(i * 16666667);
    assert(fabsf(runtime_drs_scale() - 0.67f) < 0.001f);
    assert(atomic_load(atomic_load(&drs_data)) >> 32 == 1);
    runtime_drs_set_min(0.8f); runtime_frame_step_update(200 * 16666667ull);
    for (uint64_t i = 201; i < 400; i++) runtime_frame_step_update(i * 16666667);
    assert(fabsf(runtime_drs_scale() - 0.8f) < 0.001f);
    runtime_drs_set(0); runtime_frame_step_update(400 * 16666667ull);
    assert(!runtime_drs_enabled()); assert(atomic_load(atomic_load(&drs_data)) >> 32 == 0);
    drs_fixed = 1; runtime_drs_set(0); runtime_frame_step_update(401 * 16666667ull);
    assert(atomic_load(atomic_load(&drs_data)) >> 32 == 1); assert(runtime_drs_scale() == 1);
    runtime_drs_set_target_ms(NAN); assert(atomic_load(&drs_target) == 16.7f);
    runtime_drs_set_target_ms(INFINITY); assert(atomic_load(&drs_target) == 16.7f);
    atomic_store(&drs_data, NULL); free(m.base);
    puts("{\"probe\":\"drs_runtime\",\"failures\":0}");
}

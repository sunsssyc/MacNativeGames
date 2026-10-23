/* Test settings.txt (games/totk/runtime/settings_file.h) with synthetic files: the parser and its line numbers, the presets
   and the preset the values match, the file the settings window writes, and the environment the launcher sets from it. */
#include "../games/totk/runtime/settings_file.h"
#include <stdio.h>

static int failures;
static void expect(int ok, const char *what) { if (!ok) { fprintf(stderr, "FAIL: %s\n", what); failures++; } }

/* The variables settings_env sets, as one "NAME=value@line;" string. */
static char envlog[2048];
static void record(const char *name, const char *value, int line, void *ctx) {
    (void)ctx; size_t n = strlen(envlog);
    snprintf(envlog + n, sizeof envlog - n, "%s=%s@%d;", name, value, line);
}
static const char *env_of(const char *text, unsigned caps) {
    Settings s; settings_defaults(&s); const char *error = NULL; envlog[0] = 0;
    if (settings_parse(text, &s, &error)) return "PARSE ERROR";
    settings_env(&s, caps, record, NULL);
    return envlog;
}
static int parse(const char *text, Settings *s, const char **error) { settings_defaults(s); *error = NULL; return settings_parse(text, s, error); }
/* The line of the first error in text, -1 when it parsed (and then it must not have changed anything). */
static int bad_line(const char *text) {
    Settings s, before; const char *error = NULL; settings_defaults(&s); before = s;
    int line = settings_parse(text, &s, &error);
    expect(!line || (error && *error), "a bad line names its problem");
    expect(!line || !memcmp(&s, &before, sizeof s), "a bad file changes nothing");
    return line ? line : -1;
}

enum { ALL = SETTINGS_CAN_RENDER_RES | SETTINGS_CAN_NATIVE_2K | SETTINGS_CAN_ASPECT | SETTINGS_CAN_ASPECT_FIT };

int main(void) {
    Settings s; const char *error;

    /* An empty file (or only comments) gives nothing: every variable keeps the runtime's default. */
    expect(!parse("", &s, &error) && !s.has, "empty file");
    expect(!parse("# just a note\n\n   \n\t# another\n", &s, &error) && !s.has, "comments and blank lines");
    expect(!strcmp(env_of("", ALL), ""), "no keys: no variables");

    /* Every key, its spellings, comments after values, CRLF, tabs and case. */
    expect(!parse("FPS_CAP = 60 # steady\r\n\tdrs=1\r\ndrs_min = 0.5\nrender_res = 2560X1440\noutput = 2K\npicture = MetalFX\n"
                  "taa = 1\naniso = 16\ninterpolation = 30+30\naspect = 21:9\n", &s, &error), "all keys");
    expect(s.fps_cap == 60 && s.drs == 1 && fabsf(s.drs_min - 0.5f) < 1e-6f && s.render_w == 2560 && s.render_h == 1440 &&
           s.output == CANVAS_2K && s.picture == PICTURE_METALFX && s.taa == 1 && s.aniso == 16 && s.interpolation == MFX_30 &&
           s.aspect == ASPECT_STEP_WIDE, "all keys: values");
    expect(s.has == ((1u << SK_COUNT) - 1 - (1u << SK_PRESET)), "all keys: given");
    expect(s.line[SK_FPS_CAP] == 1 && s.line[SK_DRS] == 2 && s.line[SK_ASPECT] == 10, "all keys: lines");
    expect(!parse("interpolation = half\naspect = fit\n", &s, &error) && s.interpolation == MFX_HALF && s.aspect == ASPECT_STEP_FIT, "half, fit");
    expect(!parse("interpolation = max\naspect = 16:9\npicture = native\n", &s, &error) && s.interpolation == MFX_MAX &&
           s.aspect == ASPECT_STEP_GAME && s.picture == PICTURE_NATIVE, "max, 16:9, native");
    expect(!parse("render_res = 0\nfps_cap = 0\naniso = 0\n", &s, &error) && !s.render_w && !s.render_h && !s.fps_cap && !s.aniso, "zeros");
    expect(!parse("render_res = 1280x720\n", &s, &error) && s.render_w == 1280 && s.render_h == 720, "a scene up to 1600x900 needs no heap layout");
    expect(!parse("render_res = 1920x1080\n", &s, &error) && s.render_w == 1920, "1920x1080 has a heap layout");
    expect(!parse("taa = 1\ntaa = 0\n", &s, &error) && s.taa == 0 && s.line[SK_TAA] == 2, "a later line for the same key wins");
    expect(!parse("fps_cap = 45", &s, &error) && s.fps_cap == 45, "last line without a newline; other caps than the window's");

    /* Bad lines: the first one is named, nothing is taken. */
    expect(bad_line("fps_cap = 60\nfps_caps = 60\n") == 2, "unknown key");
    expect(bad_line("\n# note\ntaa 1\n") == 3, "missing equals sign");
    expect(bad_line("taa =\n") == 1, "missing value");
    expect(bad_line("= 1\n") == 1, "missing key");
    expect(bad_line("taa = 1 0\n") == 1, "two values");
    expect(bad_line("taa = 2\n") == 1 && bad_line("taa = on\n") == 1 && bad_line("drs = yes\n") == 1, "taa / drs are 0 or 1");
    expect(bad_line("fps_cap = 20\n") == 1 && bad_line("fps_cap = 144\n") == 1 && bad_line("fps_cap = 60fps\n") == 1 &&
           bad_line("fps_cap = -1\n") == 1, "fps cap range: 30 to 120 (above, 1.4.3 would run fast)");
    expect(bad_line("drs_min = 0.4\n") == 1 && bad_line("drs_min = 1.1\n") == 1 && bad_line("drs_min = 67%\n") == 1, "drs_min range");
    expect(bad_line("render_res = 1600\n") == 1 && bad_line("render_res = 2048x1152\n") == 1 && bad_line("render_res = 32x32\n") == 1 &&
           bad_line("render_res = 1920x1080x\n") == 1 && bad_line("render_res = 5000x2000\n") == 1,
           "render sizes: malformed, out of range or without a heap layout");
    expect(bad_line("output = 4k\n") == 1 && bad_line("picture = fsr\n") == 1 && bad_line("interpolation = on\n") == 1 &&
           bad_line("aspect = 32:9\n") == 1 && bad_line("aniso = 17\n") == 1 && bad_line("preset = ultra\n") == 1, "unknown words");
    expect(bad_line("taa = 1\npreset = balanced\nrender_res = 2560x1600\n") == 3, "a bad line after a preset");
    expect(bad_line("aniso = 000000000000000000000000000000016\n") == 1, "a value too long");

    /* Presets: the preset's values; keys the file gives win wherever the preset line is; the aspect ratio is not a
       preset's. */
    expect(!parse("preset = performance\n", &s, &error) && s.fps_cap == 60 && !s.drs && !s.render_w && s.output == CANVAS_1080P &&
           s.picture == PICTURE_OFF && !s.taa && s.aniso == 16 && s.interpolation == MFX_OFF && s.has == (SETTINGS_PRESET_KEYS | 1u << SK_PRESET),
           "performance");
    expect(!parse("preset = BALANCED\n", &s, &error) && s.picture == PICTURE_METALFX && s.taa && s.output == CANVAS_1080P && !s.drs, "balanced");
    expect(!parse("preset = quality\n", &s, &error) && s.render_w == 2560 && s.render_h == 1440 && s.output == CANVAS_2K &&
           s.picture == PICTURE_NATIVE && s.drs && fabsf(s.drs_min - 0.67f) < 1e-6f && s.taa && s.fps_cap == 60, "quality");
    expect(!parse("taa = 0\npreset = balanced\n", &s, &error) && !s.taa && s.picture == PICTURE_METALFX && s.line[SK_TAA] == 1 &&
           s.line[SK_PICTURE] == 0, "a key before the preset line wins over it");
    expect(!parse("preset = quality\nfps_cap = 40\n", &s, &error) && s.fps_cap == 40 && s.drs, "a key after it too");
    expect(!parse("aspect = fit\npreset = quality\n", &s, &error) && s.aspect == ASPECT_STEP_FIT, "the preset keeps the aspect ratio");
    expect(!parse("preset = custom\n", &s, &error) && s.has == 1u << SK_PRESET && s.preset == PRESET_CUSTOM && !s.fps_cap, "custom sets nothing");
    for (int p = 0; p < PRESET_CUSTOM; p++) {
        settings_defaults(&s); settings_preset(&s, p);
        expect(settings_matching_preset(&s) == p, "a preset's values match it");
        Settings t = s; t.aspect = ASPECT_STEP_WIDE;
        expect(settings_matching_preset(&t) == p, "the aspect ratio does not count");
        t = s; t.taa = !t.taa; expect(settings_matching_preset(&t) == PRESET_CUSTOM, "one option changed: custom");
        t = s; t.fps_cap = 90; expect(settings_matching_preset(&t) == PRESET_CUSTOM, "the cap changed: custom");
        t = s; t.drs_min = 0.75f; expect(settings_matching_preset(&t) == PRESET_CUSTOM, "drs_min changed: custom");
        t = s; t.interpolation = MFX_HALF; expect(settings_matching_preset(&t) == PRESET_CUSTOM, "interpolation changed: custom");
    }
    settings_defaults(&s);
    expect(settings_matching_preset(&s) == PRESET_CUSTOM, "the runtime's defaults are no preset (no cap)");

    /* The file the window writes reads back to the same values, with the preset they match. */
    for (int p = 0; p <= PRESET_CUSTOM; p++) {
        Settings w; settings_defaults(&w); settings_preset(&w, p == PRESET_CUSTOM ? PRESET_BALANCED : p);
        if (p == PRESET_CUSTOM) { w.render_w = 1280; w.render_h = 720; w.aniso = 4; w.interpolation = MFX_HALF; w.aspect = ASPECT_STEP_FIT; w.drs_min = 0.83f; w.fps_cap = 0; }
        settings_clamp(&w);
        char text[4096]; int n = settings_format(&w, text, sizeof text);
        expect(n > 0 && (size_t)n < sizeof text, "the file fits");
        Settings r; expect(!parse(text, &r, &error), "the window's file parses");
        expect(r.has == ((1u << SK_COUNT) - 1) && r.preset == p, "every key and the matching preset");
        expect(r.fps_cap == w.fps_cap && r.drs == w.drs && fabsf(r.drs_min - w.drs_min) < 0.005f && r.render_w == w.render_w &&
               r.render_h == w.render_h && r.output == w.output && r.picture == w.picture && r.taa == w.taa && r.aniso == w.aniso &&
               r.interpolation == w.interpolation && r.aspect == w.aspect, "round trip");
        expect(settings_matching_preset(&r) == p, "read back: the same preset");
    }
    /* Whatever the running game started with, the window writes a file the launcher takes. */
    Settings odd; settings_defaults(&odd);
    odd.fps_cap = 3; odd.drs = 7; odd.drs_min = 0.2f; odd.render_w = 2048; odd.render_h = 1152; odd.output = 9; odd.picture = -1;
    odd.aniso = 32; odd.interpolation = 8; odd.aspect = -4; odd.taa = 5;
    settings_clamp(&odd);
    { char text[4096]; settings_format(&odd, text, sizeof text); Settings r;
      expect(!parse(text, &r, &error), "a clamped odd state parses");
      expect(r.fps_cap == 30 && r.drs == 1 && fabsf(r.drs_min - 0.5f) < 1e-6f && !r.render_w && r.output == CANVAS_1080P &&
             r.picture == PICTURE_OFF && r.aniso == 16 && r.interpolation == MFX_OFF && r.aspect == ASPECT_STEP_GAME && r.taa == 1, "clamped"); }
    odd.drs_min = NAN; settings_clamp(&odd); expect(odd.drs_min == 0.5f, "NaN drs_min");
    odd.fps_cap = 240; settings_clamp(&odd); expect(odd.fps_cap == 120, "a cap above 120 is written as 120");

    /* The environment, 1.4.3: one variable per key; 1080p and picture off leave TOTK_OUTPUT_RES to auto. */
    expect(!strcmp(env_of("preset = performance\n", ALL),
                   "TOTK_FPS_CAP=60@0;TOTK_DRS=0@0;TOTK_DRS_MIN=0.67@0;TOTK_RENDER_RES=0@0;TOTK_MFX_OUTPUT=0@0;TOTK_MFX_UPSCALE=0@0;"
                   "TOTK_TAA=0@0;TOTK_ANISO=16@0;TOTK_MFX=0@0;"), "performance environment");
    expect(!strcmp(env_of("preset = balanced\n", ALL),
                   "TOTK_FPS_CAP=60@0;TOTK_DRS=0@0;TOTK_DRS_MIN=0.67@0;TOTK_RENDER_RES=0@0;TOTK_MFX_OUTPUT=1@0;TOTK_MFX_UPSCALE=1@0;"
                   "TOTK_TAA=1@0;TOTK_ANISO=16@0;TOTK_MFX=0@0;"), "balanced environment: MetalFX 2K");
    expect(!strcmp(env_of("preset = quality\n", ALL),
                   "TOTK_FPS_CAP=60@0;TOTK_DRS=1@0;TOTK_DRS_MIN=0.67@0;TOTK_RENDER_RES=2560x1440@0;TOTK_OUTPUT_RES=2560x1440@0;"
                   "TOTK_MFX_OUTPUT=0@0;TOTK_MFX_UPSCALE=0@0;TOTK_TAA=1@0;TOTK_ANISO=16@0;TOTK_MFX=0@0;"), "quality environment: native 2K");
    expect(!strcmp(env_of("taa = 1\n", ALL), "TOTK_TAA=1@1;"), "one key, one variable");
    expect(!strcmp(env_of("\noutput = 2k\n", ALL), "TOTK_OUTPUT_RES=2560x1440@2;"), "the 2K canvas alone");
    expect(!strcmp(env_of("output = 1080p\n", ALL), ""), "1080p: auto");
    expect(!strcmp(env_of("output = 2k\npicture = native\n", ALL), "TOTK_OUTPUT_RES=2560x1440@2;TOTK_MFX_OUTPUT=0@2;TOTK_MFX_UPSCALE=0@2;"),
           "2k and native: one TOTK_OUTPUT_RES");
    expect(!strcmp(env_of("interpolation = 30+30\naspect = fit\n", ALL), "TOTK_MFX=interp30@1;TOTK_ASPECT=display@2;"), "interp30, display");
    expect(!strcmp(env_of("interpolation = half\naspect = 21:9\n", ALL), "TOTK_MFX=interp@1;TOTK_ASPECT=21:9@2;"), "interp, 21:9");
    expect(!strcmp(env_of("interpolation = max\naspect = 16:9\n", ALL), "TOTK_MFX=interpmax@1;TOTK_ASPECT=0@2;"), "interpmax, 16:9");
    expect(!strcmp(env_of("render_res = 1280x720\ndrs_min = 0.833\nfps_cap = 0\n", ALL),
                   "TOTK_FPS_CAP=0@3;TOTK_DRS_MIN=0.83@2;TOTK_RENDER_RES=1280x720@1;"), "sizes and numbers as the runtime reads them");
    /* Builds that cannot use a key set nothing for it (one settings.txt serves every version). */
    const char *q = "preset = quality\naspect = fit\n";
    expect(!strstr(env_of(q, SETTINGS_CAN_NATIVE_2K | SETTINGS_CAN_ASPECT | SETTINGS_CAN_ASPECT_FIT), "TOTK_RENDER_RES") &&
           strstr(envlog, "TOTK_OUTPUT_RES=2560x1440") && strstr(envlog, "TOTK_ASPECT=display"), "1.2.1: no render size");
    expect(!strstr(env_of(q, SETTINGS_CAN_NATIVE_2K), "TOTK_ASPECT") && strstr(envlog, "TOTK_OUTPUT_RES"), "1.0.0 / 1.1.2: no TOTK_ASPECT (it stops the start there)");
    expect(!strstr(env_of(q, SETTINGS_CAN_ASPECT), "TOTK_ASPECT") && !strstr(envlog, "TOTK_OUTPUT_RES") && !strstr(envlog, "TOTK_RENDER_RES") &&
           strstr(envlog, "TOTK_TAA=1"), "Breath of the Wild 1.9.0: no fit, native 2K or render size");
    expect(strstr(env_of("aspect = 21:9\n", SETTINGS_CAN_ASPECT), "TOTK_ASPECT=21:9") != NULL, "Breath of the Wild 1.9.0: 21:9");
    expect(!strcmp(env_of("aspect = 21:9\npicture = native\n", 0), "TOTK_MFX_OUTPUT=0@2;TOTK_MFX_UPSCALE=0@2;"), "Breath of the Wild 1.6.0");
#if defined(TOTK_GAME_V143)
    expect(settings_build_caps() == ALL, "this build: 1.4.3");
#endif

    /* The launcher's setter: a variable already in the environment wins. */
    unsetenv("TOTK_SETTINGS_TEST_A"); setenv("TOTK_SETTINGS_TEST_B", "kept", 1);
    expect(!strcmp(settings_setenv("TOTK_SETTINGS_TEST_A", "1"), "1") && !strcmp(getenv("TOTK_SETTINGS_TEST_A"), "1"), "unset: set");
    expect(!strcmp(settings_setenv("TOTK_SETTINGS_TEST_B", "file"), "kept") && !strcmp(getenv("TOTK_SETTINGS_TEST_B"), "kept"), "open --env wins");
    expect(!strcmp(settings_setenv("TOTK_SETTINGS_TEST_A", "2"), "1"), "set once");

    if (failures) return 1;
    puts("PASS settings.txt: parser, presets, the window's file, environment");
    return 0;
}

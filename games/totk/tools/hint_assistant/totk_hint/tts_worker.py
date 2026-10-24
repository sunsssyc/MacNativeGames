"""The 朗读 voice: Qwen3-TTS (0.6B Base, 4-bit MLX) in its own Python environment, started by voice.py.

    <tts venv>/bin/python -I tts_worker.py <model folder>

Reads one JSON request per line on standard input and answers one JSON line on standard output:
    {"text": "...", "out": "/path/page.wav", "ref_audio": "/path/ref.wav", "ref_text": "...", "seed": 7}   (seed optional)
    -> {"ok": true, "seconds": 3.1, "audio_seconds": 6.4}  |  {"ok": false, "error": "..."}
The first line it writes is {"ready": true, "sample_rate": 24000} once the model is loaded. It never imports the hint
package (a separate interpreter with mlx-audio, not the game's Python) and exits when standard input closes."""
import json
import os
import sys
import time
import wave


def write_wav(path, audio, sample_rate):
    import numpy as np
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype('<i2')
    tmp = f'{path}.part'
    with wave.open(tmp, 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(pcm.tobytes())
    os.replace(tmp, path)


def main(argv):
    import contextlib
    import mlx.core as mx
    import numpy as np
    from mlx_audio.tts.utils import load_model
    with contextlib.redirect_stdout(sys.stderr):   # the loader's prints are not replies
        model = load_model(argv[1])
    print(json.dumps({'ready': True, 'sample_rate': model.sample_rate}), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            t0 = time.monotonic()
            if request.get('seed') is not None:
                mx.random.seed(int(request['seed']))
            if not request.get('ref_audio') or not request.get('ref_text'):
                raise ValueError('a reference voice is required')   # Base has no voice of its own: it never stops
            # About 4 Chinese characters a second at 12.5 tokens a second, with room for pauses.
            limit = max(64, 8 * len(request['text']))
            with contextlib.redirect_stdout(sys.stderr):
                chunks = [np.asarray(r.audio, dtype=np.float32) for r in model.generate(
                    text=request['text'], ref_audio=request['ref_audio'], ref_text=request['ref_text'],
                    lang_code='chinese', split_pattern='\n', max_tokens=limit)]
            audio = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
            write_wav(request['out'], audio, model.sample_rate)
            reply = {'ok': True, 'seconds': round(time.monotonic() - t0, 2),
                     'audio_seconds': round(len(audio) / model.sample_rate, 2)}
        except Exception as e:   # one bad page must not take the voice down
            reply = {'ok': False, 'error': f'{type(e).__name__}: {e}'[:300]}
        print(json.dumps(reply, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

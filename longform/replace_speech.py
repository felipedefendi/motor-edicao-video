r"""Replaces words or passages of the narrator's speech while keeping the music bed, the duration and the
rest of the audio intact.

Usage: python longform/replace_speech.py jobs/<job> <tts.mp3> <tts_whisper.json> [--only S1,S3] [--preview]

Recipe in jobs/<job>/docs/speech_swaps.json:
  {"script": "docs/tts_script.txt",
   "swaps": [{"id": "S1", "line": 1, "target": "new words", "start": 2.24, "end": 2.76}, ...]}
- line: sentence number in the script (1-based, separated by blank lines);
- target: the words of the script that replace [start, end] of the original.

How it works, per swap:
1. aligns the script with the Whisper transcript of the generated voice (difflib) and takes the target
   span between the neighbouring anchor words; trims silence;
2. Demucs (htdemucs, 2 stems) on a +-3 s window of the original -> voice / music bed;
3. matches the RMS of the new voice to the original voice in the span; adjusts duration (atempo
   0.75-1.4, then pad/trim) to fit exactly in [start, end];
4. region = separated original bed + new voice; outside it, the original audio; 15 ms crossfade.
Output: work/voice/audio_new.wav (PCM) and work/voice/swaps/<id>.wav (for review).
"""
import difflib
import json
import os
import re
import subprocess
import sys
import unicodedata

import numpy as np
import soundfile as sf

SR = 44100


def norm(w):
    w = unicodedata.normalize("NFKD", w.lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", w)


def ff_audio(src, a=None, d=None, sr=SR):
    cmd = ["ffmpeg", "-v", "error"]
    if a is not None:
        cmd += ["-ss", f"{a:.4f}"]
    cmd += ["-i", src]
    if d is not None:
        cmd += ["-t", f"{d:.4f}"]
    cmd += ["-vn", "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def demucs_split(x):
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    global _MODEL
    if "_MODEL" not in globals():
        _MODEL = get_model("htdemucs")
        _MODEL.eval()
    wav = torch.from_numpy(x.T.copy()).float()
    ref = wav.mean(0)
    wav_n = (wav - ref.mean()) / (ref.std() + 1e-8)
    with torch.no_grad():
        out = apply_model(_MODEL, wav_n[None], device="cpu", progress=False)[0]
    out = out * (ref.std() + 1e-8) + ref.mean()
    sources = _MODEL.sources
    vocals = out[sources.index("vocals")].numpy().T
    bed = x - vocals  # bed = original - voice: adds back exactly to the original
    return vocals, bed


def rms(x):
    return float(np.sqrt(np.mean(x ** 2) + 1e-12))


def trim_silence(x, thr_db=-38):
    e = np.abs(x).max(1)
    thr = 10 ** (thr_db / 20) * max(e.max(), 1e-6)
    idx = np.where(e > thr)[0]
    if len(idx) == 0:
        return x
    return x[max(0, idx[0] - int(0.005 * SR)): idx[-1] + int(0.02 * SR)]


def fit(x, n, keep_pace=False):
    """Adjusts the duration of x to n samples: bounded atempo, then soft pad/trim."""
    factor = len(x) / n
    if keep_pace:
        if len(x) > n:
            raise ValueError("Reviewed source exceeds the window; adjust the bounds or regenerate, do not cut phonemes")
        pad = n - len(x)
        return np.pad(x, ((pad // 2, pad - pad // 2), (0, 0))), factor
    f = min(1.4, max(0.75, factor))
    if abs(f - 1) > 0.01:
        p = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-i", "-",
                            "-af", f"atempo={f:.4f}", "-f", "f32le", "-"],
                           input=x.astype(np.float32).tobytes(), capture_output=True, check=True)
        x = np.frombuffer(p.stdout, np.float32).reshape(-1, 2).copy()
    if len(x) >= n:
        x = x[:n]
        fade = min(int(0.012 * SR), n)
        x[-fade:] *= np.linspace(1, 0, fade)[:, None]
    else:
        pad = n - len(x)
        x = np.vstack([np.zeros((pad // 2, 2), np.float32), x, np.zeros((pad - pad // 2, 2), np.float32)])
    return x, factor


def locate(script_lines, tts_words, line, target):
    """Returns (t0, t1) of the target in the generated voice, using the neighbouring words as anchors."""
    expected, line_of = [], []
    for i, l in enumerate(script_lines, 1):
        for w in l.split():
            expected.append(norm(w))
            line_of.append(i)
    target_n = [norm(w) for w in target.split()]
    pos = None
    for k in range(len(expected)):
        if line_of[k] == line and expected[k:k + len(target_n)] == target_n:
            pos = k
            break
    if pos is None:
        raise ValueError(f"target '{target}' not found in line {line}")
    heard = [norm(w["word"]) for w in tts_words]
    sm = difflib.SequenceMatcher(None, expected, heard, autojunk=False)
    mapping = {}
    for blk in sm.get_matching_blocks():
        for j in range(blk.size):
            mapping[blk.a + j] = blk.b + j
    before = max((k for k in mapping if k < pos), default=None)
    after = min((k for k in mapping if k >= pos + len(target_n)), default=None)
    t0 = tts_words[mapping[before]]["end"] if before is not None else 0.0
    t1 = tts_words[mapping[after]]["start"] if after is not None else tts_words[-1]["end"] + 0.3
    # if the target itself was recognised, use its own times (tighter)
    inside = [mapping[k] for k in range(pos, pos + len(target_n)) if k in mapping]
    if len(inside) == len(target_n):
        t0 = tts_words[inside[0]]["start"]
        t1 = tts_words[inside[-1]]["end"]
    return t0, t1


def main():
    job = sys.argv[1].rstrip("\\/")
    tts, tts_json = sys.argv[2], sys.argv[3]
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    rec = json.load(open(os.path.join(job, "docs", "speech_swaps.json"), encoding="utf-8-sig"))
    if rec.get("contextual_patches"):
        raise SystemExit("The recipe has later contextual patches. Use the current audio on record and apply "
                         "incremental patches; regenerating this recipe alone would lose those corrections.")
    lines = [l.strip() for l in open(os.path.join(job, rec["script"]), encoding="utf-8").read().split("\n\n")
             if l.strip()]
    w = json.load(open(tts_json, encoding="utf-8"))
    words = [p for s in w["segments"] for p in s["words"]]
    src = os.path.join(job, "input", "original.mp4")
    tts_voice = ff_audio(tts)
    out_dir = os.path.join(job, "work", "voice", "swaps")
    os.makedirs(out_dir, exist_ok=True)

    full = ff_audio(src)
    new = full.copy()
    log = []
    for t in rec["swaps"]:
        if only and t["id"] not in only:
            continue
        a, b = t["start"], t["end"]
        auto0, auto1 = locate(lines, words, t["line"], t["target"])
        manual = "source_start" in t or "source_end" in t
        if manual and not ("source_start" in t and "source_end" in t):
            raise ValueError(f"{t['id']}: give both phonetic bounds of the source")
        t0, t1 = (float(t["source_start"]), float(t["source_end"])) if manual else (auto0, auto1)
        if not (0 <= t0 < t1 <= len(tts_voice) / SR):
            raise ValueError(f"{t['id']}: invalid source bounds")
        # reviewed manual bounds already keep the phonetic margins; do not trim again
        source_span = tts_voice[int(round(t0 * SR)): int(round(t1 * SR))]
        seg = source_span.copy() if manual else trim_silence(source_span)
        if not manual:
            print(f"WARNING {t['id']}: automatic bounds; review the source and the final seam in context", flush=True)
        win_a = max(0.0, a - 3.0)
        ia, ib = int(a * SR), int(b * SR)
        ja, jb = int(win_a * SR), int((b + 3.0) * SR)
        vocals, bed = demucs_split(full[ja:jb])
        vocals_orig = vocals[ia - ja: ib - ja]
        seg = seg * (rms(vocals_orig) / max(rms(seg), 1e-6))
        seg, factor = fit(seg, ib - ia, keep_pace=t.get("keep_pace", False))
        comp = bed[ia - ja: ib - ja] + seg
        xf = int(0.015 * SR)
        r = np.linspace(0, 1, xf)[:, None]
        orig = full[ia:ib]
        comp[:xf] = orig[:xf] * (1 - r) + comp[:xf] * r
        comp[-xf:] = comp[-xf:] * (1 - r) + orig[-xf:] * r
        new[ia:ib] = comp
        sf.write(os.path.join(out_dir, f"{t['id']}.wav"), new[max(0, ia - SR):ib + SR], SR)
        log.append(f"{t['id']}: {a:.2f}-{b:.2f}s <- tts {t0:.2f}-{t1:.2f}s  factor {factor:.2f}")
        print(log[-1], flush=True)
    if "--preview" not in sys.argv:
        dst = os.path.join(job, "work", "voice", "audio_new.wav")
        sf.write(dst, np.clip(new, -1, 1), SR, subtype="FLOAT")
        print("audio ->", dst)
    with open(os.path.join(out_dir, "log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log))


if __name__ == "__main__":
    main()

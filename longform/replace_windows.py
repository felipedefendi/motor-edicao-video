r"""Replaces ONLY the declared windows, keeping the rest of the video, the audio and the duration exactly
as in the original.

Usage:  python longform/replace_windows.py jobs/<job> [--output name.mp4] [--lossless]

Reads jobs/<job>/docs/windows.json:
[
  {"segment": 1, "start": 12.40, "end": 15.00, "clip": "work/clips/s01.mp4",
   "method": "new clip", "fade": 0.08, "clip_start": 0.0}
]
- `start`/`end`   : seconds in the ORIGINAL (the window that goes away)
- `clip`          : what goes in its place, path relative to the job
- `clip_start`    : where in the clip to start from (default 0)
- `fade`          : seconds of crossfade at each end so the seam does not jump (default 0.08; 0 disables)

Strategy: a single ffmpeg pass overlaying each clip on the original with integer frame bounds in `enable`.
Nothing is cut or concatenated, so the frame grid of the original is preserved frame by frame and the
audio can be copied without re-encoding (`-c:a copy`).

After rendering, ALWAYS run longform/audit_render.py — no audit report, no delivery.
"""
import glob
import json
import os
import subprocess
import sys

CRF = "0" if "--lossless" in sys.argv else "16"          # a visible loss in a long video reads as a patch
PRESET = "fast" if "--lossless" in sys.argv else "slow"
COLOR = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"


def ffprobe(src):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate,nb_frames", "-show_entries",
                          "format=duration", "-of", "json", src],
                         capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(out.stderr[-2000:])
    j = json.loads(out.stdout)
    v = j["streams"][0]
    n, _, d = v["r_frame_rate"].partition("/")
    return int(v["width"]), int(v["height"]), float(n) / float(d or 1), float(j["format"]["duration"])


def main():
    job = sys.argv[1].rstrip("\\/")
    output = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else "render.mp4"
    src = sorted(glob.glob(os.path.join(job, "input", "*.mp4")))[0]
    # utf-8-sig: a file written by PowerShell comes with a BOM
    windows = json.load(open(os.path.join(job, "docs", "windows.json"), encoding="utf-8-sig"))
    windows = [w for w in windows if w.get("clip")]
    if not windows:
        raise SystemExit("no window with a clip in docs/windows.json")

    W, H, FPS, DUR = ffprobe(src)
    out_dir = os.path.join(job, "output")
    history = os.path.join(out_dir, "_history")
    os.makedirs(history, exist_ok=True)
    dst = os.path.join(out_dir, output)
    if os.path.exists(dst):
        i = 1
        while os.path.exists(os.path.join(history, f"{i:02d}_{output}")):
            i += 1
        os.replace(dst, os.path.join(history, f"{i:02d}_{output}"))

    windows.sort(key=lambda w: w["start"])
    prev_end = -1.0
    for w in windows:
        if w["start"] < prev_end:
            raise SystemExit(f"overlapping windows at {w['start']}s — separate them before assembling")
        if w["end"] > DUR + 1e-3:
            raise SystemExit(f"window {w} goes past the end of the original ({DUR:.3f}s)")
        prev_end = w["end"]

    args = ["ffmpeg", "-v", "error", "-stats", "-y", "-filter_complex_threads", "1", "-threads", "2", "-i", src]
    for w in windows:
        args += ["-threads", "2", "-i", os.path.join(job, w["clip"])]

    fc, base = [], "base"
    fc.append(f"[0:v]{COLOR},fps={FPS}[base]")
    for n, w in enumerate(windows, start=1):
        a, b = float(w["start"]), float(w["end"])
        first, limit = round(a * FPS), round(b * FPS)
        a, b = first / FPS, limit / FPS
        dsec = b - a
        off = float(w.get("clip_start", 0.0))
        fade = float(w.get("fade", 0.08))
        lbl = f"c{n}"
        # clip: trim to the exact window length, match resolution/fps and shift to t=a
        v = (f"[{n}:v]{COLOR},trim=start={off}:duration={dsec},setpts=PTS-STARTPTS,"
             f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,"
             f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,format=yuva420p")
        if fade > 0:
            v += (f",fade=t=in:st=0:d={fade}:alpha=1"
                  f",fade=t=out:st={max(dsec - fade, 0):.4f}:d={fade}:alpha=1")
        v += f",setpts=PTS+{a}/TB[{lbl}]"
        fc.append(v)
        out = f"v{n}"
        fc.append(f"[{base}][{lbl}]overlay=0:0:eof_action=pass:"
                  f"enable='gte(n,{first})*lt(n,{limit})'[{out}]")
        base = out
    fc.append(f"[{base}]format=yuv420p[vout]")

    args += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "0:a?",
             "-c:v", "libx264", "-threads", "4", "-preset", PRESET, "-crf", CRF, "-pix_fmt", "yuv420p",
             "-r", f"{FPS}", "-c:a", "copy", "-movflags", "+faststart", dst]

    print(f"original {W}x{H} @ {FPS} fps, {DUR:.3f}s | {len(windows)} windows")
    p = subprocess.run(args)
    if p.returncode:
        raise SystemExit("render failed")

    w2, h2, f2, d2 = ffprobe(dst)
    print(f"render: {w2}x{h2} @ {f2} fps, {d2:.3f}s -> {dst}")
    if (w2, h2) != (W, H) or abs(d2 - DUR) > 1.0 / FPS:
        print("WARNING: render diverged from the original. Do NOT deliver; investigate first.")
    print("Next: python longform/audit_render.py " + job)


if __name__ == "__main__":
    main()

r"""Lists the scene cuts and builds a contact sheet with ONE frame per shot.

Usage:  python longform/scene_cuts.py jobs/<job> [threshold]        (default threshold 0.30)

Why this exists: a window that is going to be replaced must start and end on a CUT, not on a round
second. A seam in the middle of a shot shows; a seam on a cut does not.

Writes to jobs/<job>/work/cuts/:
  shots.json         [{"n":1,"start":0.0,"end":2.46,"duration":2.46}, ...]
  shots_000.png      6x4 sheet with the middle frame of each shot, in order
A person then reviews the sheet and decides which shots become replacement windows.
"""
import json
import os
import re
import subprocess
import sys

COLS, ROWS = 6, 4


def run(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(p.stderr[-2000:])
    return p.stdout


def main():
    job = sys.argv[1].rstrip("\\/")
    threshold = float(sys.argv[2]) if len(sys.argv) > 2 else 0.30
    src = os.path.join(job, "input", "original.mp4")
    if not os.path.exists(src):
        candidates = [f for f in os.listdir(os.path.join(job, "input")) if f.lower().endswith(".mp4")]
        src = os.path.join(job, "input", candidates[0])
    out = os.path.join(job, "work", "cuts")
    os.makedirs(out, exist_ok=True)

    duration = float(json.loads(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                     "-of", "json", src]))["format"]["duration"])
    # the lavfi movie= filter chokes on Windows paths with spaces and ':' -> read from showinfo instead
    p = subprocess.run(["ffmpeg", "-v", "info", "-i", src, "-vf",
                        f"select='gt(scene,{threshold})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    ts = sorted({round(float(m.group(1)), 3)
                 for m in re.finditer(r"pts_time:([0-9.]+)", p.stderr)})

    edges = [0.0] + [t for t in ts if 0.05 < t < duration - 0.05] + [duration]
    # number AFTER filtering: a gap in the numbering breaks the sheet (image2 stops at the hole)
    shots = [{"start": round(a, 3), "end": round(b, 3), "duration": round(b - a, 3)}
             for a, b in zip(edges[:-1], edges[1:]) if b - a > 0.08]
    for i, s in enumerate(shots, start=1):
        s["n"] = i
    with open(os.path.join(out, "shots.json"), "w", encoding="utf-8") as fh:
        json.dump(shots, fh, indent=2, ensure_ascii=False)

    # one frame from the middle of each shot
    tmp = os.path.join(out, "_frames")
    os.makedirs(tmp, exist_ok=True)
    for f in os.listdir(tmp):          # leftovers from a previous run would misalign the sheet
        os.remove(os.path.join(tmp, f))
    for f in os.listdir(out):
        if f.startswith("shots_") and f.endswith(".png"):
            os.remove(os.path.join(out, f))
    for s in shots:
        t = (s["start"] + s["end"]) / 2
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1",
             "-vf", "scale=240:-2", os.path.join(tmp, f"f{s['n']:04d}.png")])
    run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", os.path.join(tmp, "f%04d.png"),
         "-vf", f"tile={COLS}x{ROWS}:padding=4:color=0x202020", "-start_number", "0",
         os.path.join(out, "shots_%03d.png")])

    print(f"{len(shots)} shots | duration {duration:.2f}s | threshold {threshold}")
    for s in shots:
        print(f"  {s['n']:3d}  {s['start']:7.3f} -> {s['end']:7.3f}  ({s['duration']:.2f}s)")


if __name__ == "__main__":
    main()

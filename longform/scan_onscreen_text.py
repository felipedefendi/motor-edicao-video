r"""Scans the video with OCR looking for forbidden words written on screen (titles and captions).

Usage: python longform/scan_onscreen_text.py <video.mp4> <output.json> [fps=2] [terms=word1,word2]
Reads the video at 540 px wide, runs easyocr (es/en) and records every hit with time and text.
"""
import json
import re
import subprocess
import sys

import easyocr
import numpy as np

src, dst = sys.argv[1], sys.argv[2]
fps = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
terms = (sys.argv[4] if len(sys.argv) > 4 else "").split(",")
terms = [t for t in terms if t]
if not terms:
    raise SystemExit("give at least one term to search for")
W, H = 540, 960
p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-vf", f"fps={fps},scale={W}:{H}",
                      "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
reader = easyocr.Reader(["es", "en"], gpu=False, verbose=False)
hits, k = [], 0
while True:
    raw = p.stdout.read(W * H * 3)
    if len(raw) < W * H * 3:
        break
    img = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
    txt = " ".join(t for _, t, c in reader.readtext(img) if c > 0.3)
    if any(re.search(t, txt, re.I) for t in terms):
        hits.append({"t": round(k / fps, 2), "text": txt})
        print(hits[-1], flush=True)
    k += 1
json.dump(hits, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"{k} frames, {len(hits)} hits -> {dst}")

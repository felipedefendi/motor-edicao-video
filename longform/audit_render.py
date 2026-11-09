r"""Mandatory render audit before delivery.

Usage:  python longform/audit_render.py jobs/<job> [--strict]

Checks, frame by frame, that:
  1. the technical contract matches (resolution, fps, frame count, duration);
  2. the audio stream is identical to the original (MD5 of the stream);
  3. outside the replaced windows, every render frame equals the original frame;
  4. no render frame carries a trace of the old object (colour signature of its label);
and writes docs/AUDIT_<date>.md, extracting suspicious frames so a person can check them one by one.

Expected job layout:
  input/<original>.mp4
  output/<render>.mp4                  (the most recent one)
  docs/windows.json   -> [{"start": 12.4, "end": 15.0, "method": "...", "segment": 3}, ...]
  docs/old_object/*.png               crops of the old object's label (colour-signature references)

The script approves nothing by itself: it reduces the video to a short list of frames for a human to review.
"""
import datetime
import glob
import hashlib
import json
import os
import subprocess
import sys

import cv2
import numpy as np

BINS = (12, 8, 8)          # H, S, V
SUSPECT_THRESHOLD = 0.72   # histogram correlation above this = look at the frame
DIFF_THRESHOLD = 0.0 if "--strict" in sys.argv else 1.0   # mean absolute diff above this = frame changed


def run(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(f"failed: {' '.join(args[:4])}...\n{p.stderr[-2000:]}")
    return p.stdout


def ffprobe_video(src):
    return json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height,r_frame_rate,nb_frames", "-show_entries",
                           "format=duration", "-of", "json", src]))


def md5_audio(src):
    out = run(["ffmpeg", "-v", "error", "-i", src, "-vn", "-c:a", "copy", "-f", "md5", "-"])
    return out.strip().replace("MD5=", "")


def hist(img):
    h = cv2.calcHist([cv2.cvtColor(img, cv2.COLOR_BGR2HSV)], [0, 1, 2], None, BINS,
                     [0, 180, 0, 256, 0, 256])
    return cv2.normalize(h, h).flatten()


def references(job):
    d = os.path.join(job, "docs", "old_object")
    out = []
    for p in sorted(glob.glob(os.path.join(d, "*.png")) + glob.glob(os.path.join(d, "*.jpg"))):
        img = cv2.imread(p)
        if img is not None:
            out.append((os.path.basename(p), hist(img)))
    return out


def main():
    job = sys.argv[1].rstrip("\\/")
    inputs = glob.glob(os.path.join(job, "input", "*.mp4"))
    renders = sorted(glob.glob(os.path.join(job, "output", "*.mp4")), key=os.path.getmtime)
    if not inputs or not renders:
        raise SystemExit("need input/*.mp4 and output/*.mp4")
    original, render = inputs[0], renders[-1]
    docs = os.path.join(job, "docs")
    suspect_dir = os.path.join(job, "work", "suspects")
    os.makedirs(suspect_dir, exist_ok=True)

    wp = os.path.join(docs, "windows.json")
    windows = json.load(open(wp, encoding="utf-8-sig")) if os.path.exists(wp) else []
    if not windows:
        print("WARNING: docs/windows.json missing or empty -> item 3 of the report cannot be verified.")

    po, pr = ffprobe_video(original), ffprobe_video(render)
    vo, vr = po["streams"][0], pr["streams"][0]
    rows, failures = [], []

    def check(name, a, b):
        ok = str(a) == str(b)
        rows.append(f"| {name} | `{a}` | `{b}` | {'OK' if ok else 'FAIL'} |")
        if not ok:
            failures.append(name)

    check("width", vo["width"], vr["width"])
    check("height", vo["height"], vr["height"])
    check("fps", vo["r_frame_rate"], vr["r_frame_rate"])
    check("nb_frames", vo.get("nb_frames"), vr.get("nb_frames"))
    check("duration", round(float(po["format"]["duration"]), 3),
          round(float(pr["format"]["duration"]), 3))
    check("audio md5", md5_audio(original), md5_audio(render))

    n, _, d = vr["r_frame_rate"].partition("/")
    fps = float(n) / float(d or 1)
    inside = [(w["start"], w["end"]) for w in windows]
    refs = references(job)
    if not refs:
        print("WARNING: no crops in docs/old_object/ -> item 4 falls back to manual inspection of the contact sheets.")

    co, cr = cv2.VideoCapture(original), cv2.VideoCapture(render)
    i, changed_outside, suspects = 0, [], []
    count_outside, max_diff_outside = 0, 0.0
    while True:
        oko, fo = co.read()
        okr, fr = cr.read()
        if not (oko and okr):
            break
        t = i / fps
        in_window = any(round(a * fps) <= i < round(b * fps) for a, b in inside)
        if not in_window and fo.shape == fr.shape:
            diff = float(np.mean(cv2.absdiff(fo, fr)))
            count_outside += 1
            max_diff_outside = max(max_diff_outside, diff)
            if diff > DIFF_THRESHOLD:
                changed_outside.append(round(t, 3))
        if refs:
            hr = hist(fr)
            for name, href in refs:
                c = float(cv2.compareHist(hr, href, cv2.HISTCMP_CORREL))
                if c >= SUSPECT_THRESHOLD:
                    suspects.append({"t": round(t, 3), "frame": i, "ref": name, "correl": round(c, 3)})
                    cv2.imwrite(os.path.join(suspect_dir, f"f{i:06d}_t{t:08.3f}.png"), fr)
                    break
        i += 1
    co.release()
    cr.release()

    today = datetime.date.today().isoformat()
    L = [f"# Render audit — {today}", "",
         f"- original: `{os.path.abspath(original)}`", f"- render: `{os.path.abspath(render)}`",
         f"- frames compared: {i}", f"- declared replaced windows: {len(windows)}", "",
         "## 1-2. Technical contract and audio", "",
         "| item | original | render | |", "|---|---|---|---|", *rows, "",
         "## 3. Frames outside the replaced windows", ""]
    if not inside:
        L.append("NOT VERIFIED — `docs/windows.json` missing.")
    elif changed_outside:
        L.append(f"**FAIL: {len(changed_outside)} frames changed outside the windows.** "
                 f"First timestamps: {changed_outside[:20]}")
        failures.append("frames outside windows")
    elif DIFF_THRESHOLD == 0:
        L.append(f"OK — {count_outside} frames outside the windows decode to pixels identical to the original; "
                 f"largest mean difference = {max_diff_outside}. Strict check, no tolerance for re-encoding.")
    else:
        L.append(f"OK — no frame outside the windows shows a perceptible change "
                 f"(mean diff < {DIFF_THRESHOLD} of 255). This is not byte equality: H.264 re-encoding "
                 f"adds noise around 0.2, and the threshold exists to tolerate it.")
    L += ["", "## 4. Traces of the old object", ""]
    if not refs:
        L.append("NOT VERIFIED automatically — no reference crops in `docs/old_object/`. "
                 "Check the render contact sheets instead.")
    elif suspects:
        L.append(f"**{len(suspects)} suspicious frames** extracted to `work/suspects/` — "
                 "review one by one before any delivery:")
        L += ["", "| frame | t (s) | reference | correl |", "|---|---|---|---|"]
        L += [f"| {s['frame']} | {s['t']} | {s['ref']} | {s['correl']} |" for s in suspects[:200]]
        if len(suspects) > 200:
            L.append(f"| ... | +{len(suspects) - 200} | | |")
    else:
        L.append("No frame above the similarity threshold against the old label.")
    L += ["", "## 5. What this audit does NOT verify", "",
          "Perceived motion, pacing and how natural the seam looks. That remains a human judgement, "
          "watching the video. The audit also cannot recognise the old object when it appears in a colour "
          "very different from the reference crops — the crops must cover every angle and lighting "
          "condition in which it appeared.", "",
          f"## Verdict: {'REJECTED — ' + ', '.join(sorted(set(failures))) if failures else 'passed the automatic checks'}"]
    if not failures and suspects:
        L[-1] += " (with suspicious frames to review by hand)"

    p = os.path.join(docs, f"AUDIT_{today}.md")
    open(p, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"report: {p}")
    print(L[-1])


if __name__ == "__main__":
    main()

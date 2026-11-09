"""Broken lip-sync detector for presenter clips.

For each clip: tracks the head by template (eyes + nose) at 15 fps, crops the aligned mouth and measures
the motion between frames. Active speech = inside a Whisper word. Speech with a still mouth
(< REL_THR of the median) for longer than MIN_DUR = broken. Initial mouth position per clip: MOUTH in
job_config.py.

Output: jobs/<job>/avatar/lipsync_clips.json  {clip: {"broken": [[start, end], ...], ...}} in clip time.
Usage: python assembly/lipsync.py jobs/<job>
"""
import importlib.util
import json
import os
import sys

import cv2
import numpy as np

JOB = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else ".")
AV = os.path.join(JOB, "avatar")
TR = os.path.join(AV, "transcripts")
VARIANT = os.environ.get("JOB_VARIANT", "").strip().lower()      # <name> -> job_config_<name>.py / lipsync_clips_<name>.json
SUFFIX = "_" + VARIANT if VARIANT else ""
_spec = importlib.util.spec_from_file_location("job_config", os.path.join(JOB, f"job_config{SUFFIX}.py"))
_cfg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cfg)
CLIPS = ["hook_" + v.lower() for v in _cfg.VERSIONS] + list(_cfg.BODY)
MOUTH, MOUTH_REF = _cfg.MOUTH, _cfg.MOUTH_REF
CLIP_DIR = getattr(_cfg, "CLIP_DIR", {})


def clip_file(c, ext):
    sub = CLIP_DIR.get(c)
    if ext == "json":
        return os.path.join(AV, sub, "transcripts", c + ".json") if sub else os.path.join(TR, c + ".json")
    return os.path.join(AV, sub, c + ".mp4") if sub else os.path.join(AV, c + ".mp4")


FPS = 15
MIN_DUR = 0.40
REL_THR = 0.38      # "still" mouth = motion below 38% of the median motion during speech


def words(clip):
    with open(clip_file(clip, "json"), encoding="utf-8") as f:
        j = json.load(f)
    return [(w["start"], w["end"]) for s in j["segments"] for w in s["words"]]


def analyse(clip):
    cap = cv2.VideoCapture(clip_file(clip, "mp4"))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 24
    step = max(1, round(src_fps / FPS))
    mx, my = MOUTH.get(clip, MOUTH_REF)
    tpl = None
    times, motion, prev = [], [], None
    dx = dy = 0
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if i % step == 0:
            g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32)
            if tpl is None:   # template: eyes + nose (without the mouth), to track the head
                tpl = g[my - 130: my - 25, mx - 80: mx + 80].copy()
            else:             # search for the head in a +-50px window
                y0, x0 = max(0, my - 130 + dy - 50), max(0, mx - 80 + dx - 50)
                win = g[y0: y0 + tpl.shape[0] + 100, x0: x0 + tpl.shape[1] + 100]
                if win.shape[0] > tpl.shape[0] and win.shape[1] > tpl.shape[1]:
                    r = cv2.matchTemplate(win, tpl, cv2.TM_CCOEFF_NORMED)
                    _, _, _, loc = cv2.minMaxLoc(r)
                    dx, dy = x0 + loc[0] - (mx - 80), y0 + loc[1] - (my - 130)
            cx, cy = mx + dx, my + dy
            m = g[cy - 28: cy + 32, cx - 48: cx + 48]
            m = cv2.resize(m, (64, 40)) if m.size else np.zeros((40, 64), np.float32)
            motion.append(0.0 if prev is None else float(np.mean(np.abs(m - prev))))
            prev = m
            times.append(i / src_fps)
        i += 1
    cap.release()
    motion = np.convolve(np.array(motion), np.ones(3) / 3, mode="same")
    t = np.array(times)
    ws = words(clip)
    speaking = np.array([any(a <= x <= b for a, b in ws) for x in t])
    if speaking.sum() < 5:
        return {"broken": [], "t": t.tolist(), "motion": motion.tolist()}
    med = float(np.median(motion[speaking]))
    still = speaking & (motion < REL_THR * med)
    broken, start = [], None
    for k, s in enumerate(still):
        if s and start is None:
            start = t[k]
        if (not s or k == len(still) - 1) and start is not None:
            if t[k] - start >= MIN_DUR:
                broken.append([round(start, 2), round(t[k], 2)])
            start = None
    return {"broken": broken, "median": med, "t": t.tolist(), "motion": motion.tolist(),
            "speaking": speaking.tolist()}


if __name__ == "__main__":
    out = {}
    for c in CLIPS:
        r = analyse(c)
        out[c] = r
        print(f"{c:8s} broken: {r['broken'] if r else 'no face'}")
    with open(os.path.join(AV, f"lipsync_clips{SUFFIX}.json"), "w", encoding="utf-8") as f:
        json.dump(out, f)

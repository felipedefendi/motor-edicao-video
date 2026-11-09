r"""Puts the on-screen text of the ORIGINAL back on top of the new clip, without bringing anything from
the old object.

Usage:
  python longform/restore_text.py jobs/<job> <id> --preview <t>     # one frame, side by side
  python longform/restore_text.py jobs/<job> <id>                   # writes the clip with the text

Recipe in jobs/<job>/docs/texts.json:
{
  "5": {"clip": "work/clips/W5_new.mp4", "output": "work/clips/W5_final.mp4",
        "start": 33.167, "end": 36.333, "colour": "green", "outline": 7}
}

Why this way: the text was burned into the original video ON TOP of the old object. Cropping the text
rectangle would bring pieces of the old label along (two objects on screen). Here only the pixels whose
colour is the text colour (saturated, bright green or red) come across; the black outline is REDRAWN from
the shape of the letters, not copied. Digits, font, position and animation stay exactly as in the original.
"""
import json
import os
import subprocess
import sys

import cv2
import numpy as np

RANGES = {
    # OpenCV HSV: H 0-180. Tight S and V bounds separate the text from foliage and warm light.
    "green": [((38, 150, 150), (85, 255, 255))],
    "red": [((0, 150, 120), (8, 255, 255)), ((172, 150, 120), (180, 255, 255))],
}


def ffprobe_fps(src):
    o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate", "-of", "json", src],
                       capture_output=True, text=True)
    v = json.loads(o.stdout)["streams"][0]
    n, _, d = v["r_frame_rate"].partition("/")
    return int(v["width"]), int(v["height"]), float(n) / float(d or 1)


def text_mask(frame, colour, recipe=None):
    recipe = recipe or {}
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = np.zeros(frame.shape[:2], np.uint8)
    for lo, hi in recipe.get("hsv_ranges", RANGES[colour]):
        m |= cv2.inRange(hsv, np.array(lo), np.array(hi))
    if recipe.get("roi"):
        x0, y0, x1, y1 = recipe["roi"]
        limited = np.zeros_like(m)
        limited[y0:y1, x0:x1] = m[y0:y1, x0:x1]
        m = limited
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    close = recipe.get("close", 0)
    if close:
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((close, close), np.uint8))
    # drop small specks: on-screen text is large
    n, labels, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= 120:
            keep[labels == i] = 255
    return keep


def apply(new, orig, colour, outline, recipe=None):
    recipe = recipe or {}
    m = text_mask(orig, colour, recipe)
    if not m.any():
        return new
    ys, xs = np.nonzero(m)
    margin = max(8, outline * 6)
    x0, x1 = max(0, int(xs.min()) - margin), min(new.shape[1], int(xs.max()) + margin + 1)
    y0, y1 = max(0, int(ys.min()) - margin), min(new.shape[0], int(ys.max()) + margin + 1)
    base = new
    new, orig, m = new[y0:y1, x0:x1], orig[y0:y1, x0:x1], m[y0:y1, x0:x1]
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * outline + 1, 2 * outline + 1))
    border = cv2.dilate(m, k)
    shadow = cv2.GaussianBlur(cv2.dilate(m, k, iterations=2), (0, 0), outline)
    out = new.astype(np.float32)
    a_s = (shadow.astype(np.float32) / 255.0)[..., None] * 0.55
    out = out * (1 - a_s)                                   # soft shadow
    a_b = cv2.GaussianBlur(border, (3, 3), 0).astype(np.float32)[..., None] / 255.0
    out = out * (1 - a_b)                                   # redrawn black outline
    a_t = cv2.GaussianBlur(m, (3, 3), 0).astype(np.float32)[..., None] / 255.0
    ink = np.array(recipe["ink_bgr"], dtype=np.float32) if "ink_bgr" in recipe else orig.astype(np.float32)
    out = out * (1 - a_t) + ink * a_t   # only the text pixels come from the original
    result = base.copy()
    result[y0:y1, x0:x1] = np.clip(out, 0, 255).astype(np.uint8)
    return result


def main():
    job = sys.argv[1].rstrip("\\/")
    tid = sys.argv[2]
    t_preview = float(sys.argv[sys.argv.index("--preview") + 1]) if "--preview" in sys.argv else None
    rec = json.load(open(os.path.join(job, "docs", "texts.json"), encoding="utf-8-sig"))[tid]
    src = os.path.join(job, "input", "original.mp4")
    W, H, FPS = ffprobe_fps(src)
    co = cv2.VideoCapture(src)
    co.set(cv2.CAP_PROP_POS_FRAMES, int(round(rec["start"] * FPS)))
    cn = cv2.VideoCapture(os.path.join(job, rec["clip"]))
    n = int(round((rec["end"] - rec["start"]) * FPS))
    target = int(round((t_preview - rec["start"]) * FPS)) if t_preview is not None else -1

    writer = None
    if t_preview is None:
        dst = os.path.join(job, rec["output"])
        writer = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
             "-r", f"{FPS}", "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
             "-pix_fmt", "yuv420p", dst], stdin=subprocess.PIPE)
    k = 0
    for k in range(n + 3):
        ok1, fo = co.read()
        ok2, fn = cn.read()
        if not (ok1 and ok2):
            break
        if fn.shape[:2] != (H, W):
            fn = cv2.resize(fn, (W, H), interpolation=cv2.INTER_LANCZOS4)
        out = apply(fn, fo, rec["colour"], rec.get("outline", 7), rec)
        if t_preview is not None:
            if k == target:
                side = np.hstack([cv2.resize(fo, (W // 3, H // 3)), cv2.resize(out, (W // 3, H // 3))])
                p = os.path.join(job, "work", f"preview_text_W{tid}_{t_preview:.2f}.png")
                cv2.imwrite(p, side)
                print(f"preview (original | new with text): {p}")
                break
        else:
            writer.stdin.write(out.tobytes())
    co.release()
    cn.release()
    if writer:
        writer.stdin.close()
        writer.wait()
        print(f"{k} frames -> {os.path.join(job, rec['output'])}")


if __name__ == "__main__":
    main()

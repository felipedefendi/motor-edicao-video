r"""Composites a new object over a window of the original video, tracking the camera frame by frame.

Usage:
  python longform/composite_object.py jobs/<job> <window_id> --preview <t>   # one frame, to inspect
  python longform/composite_object.py jobs/<job> <window_id>                 # the whole window

Reads the recipe in jobs/<job>/docs/composite.json:
{
  "4": {
    "object": "library/objects/<slug>/cutouts/x.png",   # path relative to the repository root
    "start": 1.833, "end": 8.400,
    "base_x": 495, "base_y": 1530,        # centre and resting line of the new object, in the 1st frame
    "height": 980,                        # height of the new object in px
    "repair": [280, 400, 430, 580],       # x0,y0,x1,y1 of the band to rebuild (where the old object stuck out)
    "shadow": {"opacity": 0.45, "rx": 0.52, "ry": 26},
    "colour": [1.0, 1.0, 1.0],            # B,G,R gain to match the scene lighting
    "brightness": 1.0
  }
}

What the script guarantees:
- **tracking**: the global displacement of the scene is measured against the first frame of the window
  and the object follows it. Without this the object "slides" relative to the table.
- **repair**: the band where the old object stuck out is filled either by inpainting at reduced scale
  (soft, for out-of-focus backgrounds) or by mirroring the clean band above it.
- output with the exact duration of the window, at the original fps, WITHOUT audio.
"""
import json
import os
import subprocess
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ffprobe(src):
    o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate", "-of", "json", src],
                       capture_output=True, text=True)
    v = json.loads(o.stdout)["streams"][0]
    n, _, d = v["r_frame_rate"].partition("/")
    return int(v["width"]), int(v["height"]), float(n) / float(d or 1)


def repair(base, cx0, y0, cx1, y1, mode="soft", feather=25, scale=8):
    """Rebuilds the rectangle where the old object used to be.

    mode 'soft' (default, for blurred backgrounds): shrinks the frame, inpaints the thumbnail and scales it
    back up. At reduced scale the fill becomes a shapeless gradient, which is exactly what an out-of-focus
    background looks like. Avoids the rectangular seam of the mirror method.
    mode 'mirror': copies the band above, flipped. Only works when the background has continuous vertical
    structure (light beams, curtains), never with uneven lateral bokeh.
    """
    H, W = base.shape[:2]
    cx0, y0 = max(0, cx0), max(0, y0)
    cx1, y1 = min(W, cx1), min(H, y1)
    if cx1 <= cx0 or y1 <= y0:
        return base.copy()
    m = np.zeros((H, W), np.uint8)
    cv2.rectangle(m, (cx0, y0), (cx1, y1), 255, -1)

    if mode == "mirror":
        out = base.copy()
        height = y1 - y0
        band = cv2.flip(base[max(0, y0 - height):y0, cx0:cx1], 0)
        if band.shape[0] < height:
            band = cv2.resize(band, (cx1 - cx0, height), interpolation=cv2.INTER_LINEAR)
        out[y0:y1, cx0:cx1] = band[:height]
    else:
        small = cv2.resize(base, (W // scale, H // scale), interpolation=cv2.INTER_AREA)
        small_mask = cv2.resize(m, (W // scale, H // scale), interpolation=cv2.INTER_NEAREST)
        small_mask = cv2.dilate(small_mask, np.ones((3, 3), np.uint8), 1)
        fill = cv2.inpaint(small, small_mask, 6, cv2.INPAINT_TELEA)
        out = cv2.resize(fill, (W, H), interpolation=cv2.INTER_LINEAR)
        out = cv2.GaussianBlur(out, (0, 0), 3)

    a = cv2.GaussianBlur(m, (0, 0), feather).astype(np.float32)[..., None] / 255.0
    return (out.astype(np.float32) * a + base.astype(np.float32) * (1 - a)).astype(np.uint8)


def track(orb, matcher, kp0, des0, g, scale=4):
    """Similarity (scale + translation) from the first frame to this one, in full-frame pixels.

    Phase correlation only measures translation: in a shot where the camera pulls back it fails and the
    new object goes out of scale, letting the old one reappear. ORB + estimateAffinePartial2D captures scale.
    """
    kp1, des1 = orb.detectAndCompute(g, None)
    if des0 is None or des1 is None or len(kp1) < 8:
        return 1.0, 0.0, 0.0
    pairs = matcher.knnMatch(des0, des1, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < 8:
        return 1.0, 0.0, 0.0
    a = np.float32([kp0[m.queryIdx].pt for m in good])
    b = np.float32([kp1[m.trainIdx].pt for m in good])
    M, _ = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC, ransacReprojThreshold=3)
    if M is None:
        return 1.0, 0.0, 0.0
    s = float(np.hypot(M[0, 0], M[0, 1]))
    if not (0.5 < s < 2.0):
        return 1.0, 0.0, 0.0
    return s, float(M[0, 2]) * scale, float(M[1, 2]) * scale


def shadow(base, cx, by, width, opacity, rx, ry, blur=35):
    """Soft contact shadow. A hard ellipse gives the composite away instantly."""
    m = np.zeros(base.shape[:2], np.float32)
    cv2.ellipse(m, (int(cx), int(by) - 6), (int(width * rx), int(ry)), 0, 0, 360, 1.0, -1)
    m = cv2.GaussianBlur(m, (0, 0), blur)[..., None] * opacity
    base[:] = (base.astype(np.float32) * (1 - m)).astype(np.uint8)


def place(base, obj, cx, by, height, colour, brightness):
    oh, ow = obj.shape[:2]
    f = height / oh
    p = cv2.resize(obj, (max(1, int(ow * f)), int(height)), interpolation=cv2.INTER_AREA)
    h2, w2 = p.shape[:2]
    rgb = p[:, :, :3].astype(np.float32) * np.array(colour, np.float32) * brightness
    rgb = np.clip(rgb, 0, 255)
    x, y = int(cx - w2 / 2), int(by - h2)
    H, W = base.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w2), min(H, y + h2)
    if x1 <= x0 or y1 <= y0:
        return
    a = (p[y0 - y:y1 - y, x0 - x:x1 - x, 3:4].astype(np.float32) / 255.0)
    roi = base[y0:y1, x0:x1].astype(np.float32)
    base[y0:y1, x0:x1] = (rgb[y0 - y:y1 - y, x0 - x:x1 - x] * a + roi * (1 - a)).astype(np.uint8)


def main():
    job = sys.argv[1].rstrip("\\/")
    wid = sys.argv[2]
    t_preview = float(sys.argv[sys.argv.index("--preview") + 1]) if "--preview" in sys.argv else None

    rec = json.load(open(os.path.join(job, "docs", "composite.json"), encoding="utf-8-sig"))[wid]
    src = os.path.join(job, "input", "original.mp4")
    W, H, FPS = ffprobe(src)
    obj = cv2.imread(os.path.join(ROOT, rec["object"]), cv2.IMREAD_UNCHANGED)
    if obj is None or obj.shape[2] != 4:
        raise SystemExit("the object cutout needs an alpha channel")

    rx0, ry0, rx1, ry1 = rec["repair"]
    sh = rec.get("shadow", {"opacity": 0.45, "rx": 0.52, "ry": 26})
    colour = rec.get("colour", [1.0, 1.0, 1.0])
    brightness = rec.get("brightness", 1.0)
    width = obj.shape[1] * rec["height"] / obj.shape[0]

    cap = cv2.VideoCapture(src)
    i0 = int(round(rec["start"] * FPS))
    n = int(round((rec["end"] - rec["start"]) * FPS))
    cap.set(cv2.CAP_PROP_POS_FRAMES, i0)

    writer, ref, kp0, des0 = None, None, None, None
    orb = cv2.ORB_create(1500)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    if t_preview is None:
        os.makedirs(os.path.join(job, "work", "clips"), exist_ok=True)
        dst = os.path.join(job, "work", "clips", f"W{wid}_2d.mp4")
        writer = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
             "-s", f"{W}x{H}", "-r", f"{FPS}", "-i", "-", "-an",
             "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", dst],
            stdin=subprocess.PIPE)

    target = int(round((t_preview - rec["start"]) * FPS)) if t_preview is not None else -1
    for k in range(n):
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(f, (W // 4, H // 4)), cv2.COLOR_BGR2GRAY)
        if ref is None:
            ref = g
            kp0, des0 = orb.detectAndCompute(ref, None)
            s, dx, dy = 1.0, 0.0, 0.0
        else:
            s, dx, dy = track(orb, matcher, kp0, des0, g)
        # scale AND position: translation alone is not enough when the camera dollies out
        cx = rec["base_x"] * s + dx
        by = rec["base_y"] * s + dy
        height = rec["height"] * s
        w = width * s
        out = repair(f, int(rx0 * s + dx), int(ry0 * s + dy), int(rx1 * s + dx), int(ry1 * s + dy),
                     rec.get("repair_mode", "soft"), rec.get("feather", 25))
        shadow(out, cx, by, w, sh["opacity"], sh["rx"], sh["ry"], sh.get("blur", 35))
        place(out, obj, cx, by, height, colour, brightness)
        if t_preview is not None:
            if k == target:
                p = os.path.join(job, "work", f"preview_W{wid}_{t_preview:.2f}.png")
                cv2.imwrite(p, out)
                print(f"preview: {p}  (offset dx={dx:.1f} dy={dy:.1f})")
                break
        else:
            writer.stdin.write(out.tobytes())
    cap.release()
    if writer:
        writer.stdin.close()
        writer.wait()
        print(f"{n} frames -> {os.path.join(job, 'work', 'clips', f'W{wid}_2d.mp4')}")


if __name__ == "__main__":
    main()

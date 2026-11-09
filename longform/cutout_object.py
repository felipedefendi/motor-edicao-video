r"""Cuts an object out of a photo with a plain background and saves a PNG with alpha (+ checkerboard preview).

Usage:  python longform/cutout_object.py <photo.png> <output.png> [--margin 6]

How it decides what is background: takes the median colour of the outer border of the image, marks as
background everything close to that colour, keeps the largest remaining connected component, fills holes
(a dark label or a reflection must not become a hole) and softens the edge so the cutout does not look
jagged when composited.

ALWAYS look at the preview before using it: a strong shadow on the background, or an object the same
colour as the background, break the method.
"""
import os
import sys

import cv2
import numpy as np


def cutout(src, dst, margin=6, tolerance=None):
    img = cv2.imread(src, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"could not open {src}")
    h, w = img.shape[:2]
    m = margin
    border = np.concatenate([img[:m].reshape(-1, 3), img[-m:].reshape(-1, 3),
                             img[:, :m].reshape(-1, 3), img[:, -m:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    noise = float(np.median(np.abs(border - bg))) or 1.0
    tolerance = tolerance if tolerance is not None else max(18.0, noise * 6)

    dist = np.linalg.norm(img.astype(np.float32) - bg, axis=2)
    mask = (dist > tolerance).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=3)

    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n < 2:
        raise SystemExit("no object found: background and object colours are too close")
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = (labels == largest).astype(np.uint8) * 255

    # fill internal holes (dark label, reflection) without eating the silhouette
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, contours, -1, 255, cv2.FILLED)
    mask = filled

    alpha = cv2.GaussianBlur(mask, (5, 5), 0)
    x, y, bw, bh = cv2.boundingRect(mask)
    out = np.dstack([img, alpha])[y:y + bh, x:x + bw]
    cv2.imwrite(dst, out)

    # checkerboard preview, to spot edge failures and holes
    board = np.zeros((bh, bw, 3), np.uint8)
    q = 16
    for i in range(0, bh, q):
        for j in range(0, bw, q):
            board[i:i + q, j:j + q] = 200 if ((i // q + j // q) % 2 == 0) else 120
    a = out[:, :, 3:4].astype(np.float32) / 255.0
    preview = (out[:, :, :3].astype(np.float32) * a + board.astype(np.float32) * (1 - a)).astype(np.uint8)
    pv = os.path.splitext(dst)[0] + "_preview.png"
    cv2.imwrite(pv, preview)
    print(f"background {bg.astype(int).tolist()} | tolerance {tolerance:.1f} | cutout {bw}x{bh}")
    print(f"  {dst}\n  {pv}  <- look at this one before using")


if __name__ == "__main__":
    positional = [x for x in sys.argv[1:] if not x.startswith("--")]
    margin = int(sys.argv[sys.argv.index("--margin") + 1]) if "--margin" in sys.argv else 6
    cutout(positional[0], positional[1], margin)

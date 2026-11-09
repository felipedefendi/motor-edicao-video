"""Breaks reference videos down for study: technical metadata, a frame every 5 s, a 20-frame overview,
scene cuts by visual change, dominant colours and contact sheets.

Usage: python analysis/extract_frames.py <root> [<id> ...]

<root> holds one folder per reference with original/*.mp4. Output goes to <reference>/analysis/,
<reference>/frames/ and <reference>/scene_frames/.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

TIMELINE_STEP = 5.0
SCENE_SAMPLE_FPS = 2.0
SCENE_THRESHOLD = 0.32
MIN_SCENE_GAP = 1.0


def reference_id(ref_dir: Path) -> str:
    config = ref_dir / "analysis" / "dossier_config.json"
    if config.exists():
        return json.loads(config.read_text(encoding="utf-8"))["id"]
    return ref_dir.name.split("_", 1)[0]


def find_references(root: Path) -> list[Path]:
    return sorted({path.parent.parent for path in root.rglob("original/*.mp4")})


def probe(path: Path) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
            "-of", "json", str(path),
        ],
        check=True, capture_output=True, text=True, encoding="utf-8",
    )
    return json.loads(result.stdout)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def save_frame(cap: cv2.VideoCapture, t: float, target: Path) -> np.ndarray | None:
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    if not ok:
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return frame


def frame_signature(frame: np.ndarray) -> np.ndarray:
    small = cv2.resize(frame, (160, 90))
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def dominant_colours(frame: np.ndarray, n: int = 5) -> list[str]:
    rgb = cv2.cvtColor(cv2.resize(frame, (80, 80)), cv2.COLOR_BGR2RGB).reshape(-1, 3).astype(np.float32)
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
    _, labels, centers = cv2.kmeans(rgb, n, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=n)
    order = np.argsort(counts)[::-1]
    return ["#%02X%02X%02X" % tuple(int(v) for v in centers[i]) for i in order]


def contact_sheet(items: list[tuple[Path, str]], target: Path, columns: int = 4) -> None:
    if not items:
        return
    thumb_w, thumb_h, label_h = 270, 480, 34
    rows = math.ceil(len(items) / columns)
    canvas = Image.new("RGB", (columns * thumb_w, rows * (thumb_h + label_h)), "#111111")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    for i, (path, label) in enumerate(items):
        image = Image.open(path).convert("RGB")
        image.thumbnail((thumb_w, thumb_h))
        x = (i % columns) * thumb_w + (thumb_w - image.width) // 2
        y = (i // columns) * (thumb_h + label_h)
        canvas.paste(image, (x, y))
        draw.text(((i % columns) * thumb_w + 8, y + thumb_h + 5), label, fill="white", font=font)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, quality=91)


def process(ref_dir: Path) -> None:
    video = next((ref_dir / "original").glob("*.mp4"))
    raw_probe = probe(video)
    duration = float(raw_probe["format"]["duration"])
    video_stream = next(s for s in raw_probe["streams"] if s["codec_type"] == "video")
    metadata = {
        "id": reference_id(ref_dir),
        "original_file": video.name,
        "sha256": sha256(video),
        "duration_s": round(duration, 3),
        "resolution": f"{video_stream.get('width')}x{video_stream.get('height')}",
        "fps": video_stream.get("r_frame_rate"),
        "video_codec": video_stream.get("codec_name"),
        "size_bytes": int(raw_probe["format"]["size"]),
        "streams": raw_probe["streams"],
    }
    (ref_dir / "analysis").mkdir(parents=True, exist_ok=True)
    (ref_dir / "analysis" / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    cap = cv2.VideoCapture(str(video))
    timeline_dir = ref_dir / "frames" / "timeline_5s"
    timeline_items: list[tuple[Path, str]] = []
    palette: dict[str, list[str]] = {}
    t = 0.0
    while t < duration:
        frame_path = timeline_dir / f"t_{t:07.2f}s.jpg"
        frame = save_frame(cap, t, frame_path)
        if frame is not None:
            timeline_items.append((frame_path, f"{t:06.1f}s"))
            palette[f"{t:.2f}"] = dominant_colours(frame)
        t += TIMELINE_STEP

    overview_times = np.linspace(0, max(0, duration - 0.05), 20)
    overview_items: list[tuple[Path, str]] = []
    overview_dir = ref_dir / "frames" / "overview_src"
    for idx, t_value in enumerate(overview_times, 1):
        frame_path = overview_dir / f"{idx:02d}_{t_value:07.2f}s.jpg"
        if save_frame(cap, float(t_value), frame_path) is not None:
            overview_items.append((frame_path, f"{idx:02d} · {t_value:06.1f}s"))
    contact_sheet(overview_items, ref_dir / "frames" / "overview.jpg", columns=5)

    for page_no in range(math.ceil(len(timeline_items) / 20)):
        subset = timeline_items[page_no * 20: (page_no + 1) * 20]
        contact_sheet(subset, ref_dir / "frames" / f"timeline_{page_no + 1:02d}.jpg", columns=5)

    scene_dir = ref_dir / "scene_frames"
    scene_dir.mkdir(parents=True, exist_ok=True)
    scenes: list[dict] = []
    previous_hist = None
    last_scene = -999.0
    scene_cap = cv2.VideoCapture(str(video))
    source_fps = scene_cap.get(cv2.CAP_PROP_FPS) or 30.0
    sample_every = max(1, int(round(source_fps / SCENE_SAMPLE_FPS)))
    frame_index = 0
    while True:
        ok = scene_cap.grab()
        if not ok:
            break
        if frame_index % sample_every:
            frame_index += 1
            continue
        ok, frame = scene_cap.retrieve()
        if not ok:
            frame_index += 1
            continue
        sample_t = frame_index / source_fps
        hist = frame_signature(frame)
        distance = 0.0 if previous_hist is None else float(cv2.compareHist(previous_hist, hist, cv2.HISTCMP_BHATTACHARYYA))
        is_scene = previous_hist is None or (distance >= SCENE_THRESHOLD and sample_t - last_scene >= MIN_SCENE_GAP)
        if is_scene:
            number = len(scenes) + 1
            frame_path = scene_dir / f"scene_{number:03d}_{sample_t:07.2f}s.jpg"
            cv2.imwrite(str(frame_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            scenes.append({"scene": number, "start_s": round(sample_t, 2), "visual_change": round(distance, 4),
                           "frame": str(frame_path.relative_to(ref_dir))})
            last_scene = sample_t
        previous_hist = hist
        frame_index += 1
    scene_cap.release()
    cap.release()

    for i, scene in enumerate(scenes):
        scene["end_s"] = scenes[i + 1]["start_s"] if i + 1 < len(scenes) else round(duration, 2)
        scene["duration_s"] = round(scene["end_s"] - scene["start_s"], 2)
    (ref_dir / "analysis" / "scenes_auto.json").write_text(json.dumps(scenes, ensure_ascii=False, indent=2), encoding="utf-8")
    with (ref_dir / "analysis" / "scenes_auto.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=["scene", "start_s", "end_s", "duration_s", "visual_change", "frame"])
        writer.writeheader()
        writer.writerows(scenes)
    (ref_dir / "analysis" / "sampled_palette.json").write_text(json.dumps(palette, ensure_ascii=False, indent=2), encoding="utf-8")
    scene_items = [(ref_dir / scene["frame"], f"S{scene['scene']:03d} · {scene['start_s']:06.1f}s") for scene in scenes]
    for page_no in range(math.ceil(len(scene_items) / 20)):
        subset = scene_items[page_no * 20: (page_no + 1) * 20]
        contact_sheet(subset, ref_dir / "frames" / f"scenes_{page_no + 1:02d}.jpg", columns=5)
    print(f"{reference_id(ref_dir)}: {duration:.1f}s, {len(timeline_items)} timeline frames, {len(scenes)} scenes", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("ids", nargs="*")
    args = parser.parse_args()
    root = Path(args.root)
    requested = set(args.ids)
    refs = [p for p in find_references(root) if not requested or reference_id(p) in requested]
    for ref in refs:
        process(ref)


if __name__ == "__main__":
    main()

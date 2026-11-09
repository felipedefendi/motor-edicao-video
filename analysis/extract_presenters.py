"""Extracts presenter reference frames from each reference video and writes a casting/direction sheet
plus a strategic reading of the copy.

Usage: python analysis/extract_presenters.py <root> <output_dir>

Reads <root>/presenters.json, a map of reference id -> entry:
{
  "R01": {
    "roles": [["host", [14, 31, 49]]],            # role name -> timestamps (s) to capture
    "profile": ["Role: ...", "Framing: ...", ...],
    "copy": {"hook": [...], "body": [...], "cta": [...], "wins": [...], "apply": [...]}
  },
  "R02": {"same_as": "R01", "roles": [...], "variant": "what changed in this variation"}
}
Each reference folder needs original/*.mp4, analysis/dossier_config.json and analysis/metadata.json.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFont


def resolve_entry(entries: dict, ref_id: str) -> dict:
    entry = dict(entries[ref_id])
    if "same_as" in entry:
        base = entries[entry["same_as"]]
        entry["profile"] = list(base["profile"])
        entry["copy"] = {key: list(value) for key, value in base["copy"].items()}
    return entry


def find_references(root: Path) -> dict[str, Path]:
    result = {}
    for config_path in root.rglob("analysis/dossier_config.json"):
        config = json.loads(config_path.read_text(encoding="utf-8"))
        result[config["id"]] = config_path.parent.parent
    return result


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")
    return value.lower()


def crop_presenter(frame, detector):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = () if detector.empty() else detector.detectMultiScale(gray, scaleFactor=1.08, minNeighbors=5, minSize=(45, 45))
    height, width = frame.shape[:2]
    if len(faces):
        x, y, w, h = max(faces, key=lambda f: int(f[2]) * int(f[3]))
        x0 = max(0, int(x - 0.9 * w))
        x1 = min(width, int(x + 1.9 * w))
        y0 = max(0, int(y - 0.55 * h))
        y1 = min(height, int(y + 4.1 * h))
    else:
        crop_w = int(width * 0.72)
        crop_h = int(height * 0.82)
        x0 = (width - crop_w) // 2
        x1 = x0 + crop_w
        y0 = max(0, int(height * 0.04))
        y1 = min(height, y0 + crop_h)
    return frame[y0:y1, x0:x1]


def contact_sheet(items: list[tuple[Path, str]], target: Path) -> None:
    thumb_w, thumb_h, label_h = 360, 480, 34
    columns = 2
    rows = (len(items) + columns - 1) // columns
    canvas = Image.new("RGB", (thumb_w * columns, (thumb_h + label_h) * rows), "#111111")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    for index, (path, label) in enumerate(items):
        image = Image.open(path).convert("RGB")
        image.thumbnail((thumb_w, thumb_h))
        cell_x = (index % columns) * thumb_w
        cell_y = (index // columns) * (thumb_h + label_h)
        x = cell_x + (thumb_w - image.width) // 2
        y = cell_y + (thumb_h - image.height) // 2
        canvas.paste(image, (x, y))
        draw.text((cell_x + 8, cell_y + thumb_h + 6), label, fill="white", font=font)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target, quality=92)


def bullets(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values)


def process(entries: dict, ref_id: str, ref_dir: Path, output: Path, detector) -> dict:
    entry = resolve_entry(entries, ref_id)
    config = json.loads((ref_dir / "analysis" / "dossier_config.json").read_text(encoding="utf-8"))
    metadata = json.loads((ref_dir / "analysis" / "metadata.json").read_text(encoding="utf-8"))
    video = next((ref_dir / "original").glob("*.mp4"))
    out = output / f"{ref_id}_{slug(config['name'])}"
    refs = out / "references"
    refs.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(str(video))
    sheet_items = []
    extracted = []
    for role, times in entry["roles"]:
        for sequence, timestamp in enumerate(times, 1):
            cap.set(cv2.CAP_PROP_POS_MSEC, float(timestamp) * 1000)
            ok, frame = cap.read()
            if not ok:
                continue
            stem = f"{slug(role)}_{sequence:02d}_{timestamp:06.2f}s"
            full_path = refs / f"{stem}_frame.jpg"
            crop_path = refs / f"{stem}_presenter.jpg"
            cv2.imwrite(str(full_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 94])
            cv2.imwrite(str(crop_path), crop_presenter(frame, detector), [cv2.IMWRITE_JPEG_QUALITY, 95])
            sheet_items.extend([(full_path, f"{role} · {timestamp:.1f}s · frame"), (crop_path, f"{role} · {timestamp:.1f}s · crop")])
            extracted.append((role, timestamp, full_path.name, crop_path.name))
    cap.release()
    contact_sheet(sheet_items, out / "PRESENTER_SHEET.jpg")

    refs_rows = "\n".join(
        f"| {role} | {timestamp:.2f}s | [frame](references/{full}) | [crop](references/{crop}) |"
        for role, timestamp, full, crop in extracted
    )
    variant = entry.get("variant")
    profile_doc = f"""# {ref_id} — {config['name']}

## Context

- Source reference: `{ref_dir}`
- File: `{metadata['original_file']}`
- Format: {metadata['resolution']} · duration {metadata['duration_s']:.2f}s
- Concept: {config['concept']}
{f'- Reading of the variation: {variant}' if variant else ''}

## Presenter profile

{bullets(entry['profile'])}

## Direction to preserve

- Respect the narrative function of the presenter: hook, authority, witness, bridge or CTA.
- Keep angle, camera distance, setting, wardrobe and props consistent with the message.
- Use the crops as casting and framing references; use the full frames for setting and composition.
- Do not read a change of crop or speed as a new presenter when the base take is the same.

## Extracted references

[Open contact sheet](PRESENTER_SHEET.jpg)

| Role | Time | Full frame | Presenter crop |
|---|---:|---|---|
{refs_rows}
"""
    (out / "PRESENTER_PROFILE.md").write_text(profile_doc, encoding="utf-8")

    copy = entry["copy"]
    quotes = "\n".join(f"- “{value}”" for value in config.get("key_quotes", []))
    copy_doc = f"""# Strategic copy reading — {ref_id} {config['name']}

> This reading does not change the speech. The literal copy stays in `STRUCTURED_COPY.md`; this file records inferences about the architecture of the piece.

## HOOK — why it holds attention

{bullets(copy['hook'])}

## BODY — how it sustains attention and belief

{bullets(copy['body'])}

## CTA — how it turns interest into action

{bullets(copy['cta'])}

## What likely made it work

{bullets(copy['wins'])}

## How to apply it to new pieces

{bullets(copy['apply'])}
{f'- When adapting this variation: {variant}' if variant else ''}

## Literal key quotes used as evidence

{quotes}

## Relation between copy and presenter

- Presenter: {config['presenter']}
- Hook visual: {config['hook_visual']}
- Body visual: {config['body_visual']}
- CTA visual: {config['cta_visual']}

## Internal sources

- [Structured literal copy](STRUCTURED_COPY.md)
- [Visual dossier](DOSSIER.md)
- [Low-confidence words](LOW_CONFIDENCE_WORDS.md)
"""
    (ref_dir / "analysis" / "STRATEGIC_COPY_READING.md").write_text(copy_doc, encoding="utf-8")
    return {"id": ref_id, "name": config["name"], "presenter_dir": out, "ref_dir": ref_dir, "roles": [r[0] for r in entry["roles"]]}


def write_catalog(rows: list[dict], root: Path, output: Path) -> None:
    lines = [
        "# Presenter catalogue",
        "",
        "Each folder holds full frames, presenter crops and a direction sheet. Repeated presenters are kept "
        "per id because resolution, crop, speed and function within the variation are part of the result.",
        "",
        "| ID | Piece | Extracted roles | Profile | Copy reading |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        profile = row["presenter_dir"].relative_to(output).as_posix() + "/PRESENTER_PROFILE.md"
        copy_path = Path("..") / root.name / row["ref_dir"].relative_to(root) / "analysis" / "STRATEGIC_COPY_READING.md"
        lines.append(f"| {row['id']} | {row['name']} | {', '.join(row['roles'])} | [Open]({profile}) | [Open](<{copy_path.as_posix()}>) |")
    (output / "CATALOGUE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    root, output = Path(sys.argv[1]), Path(sys.argv[2])
    entries = json.loads((root / "presenters.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(str(cascade_path)) if cascade_path.exists() else cv2.CascadeClassifier()
    refs = find_references(root)
    missing = sorted(set(entries) - set(refs))
    if missing:
        raise RuntimeError(f"Missing references: {', '.join(missing)}")
    rows = [process(entries, ref_id, refs[ref_id], output, detector) for ref_id in sorted(entries)]
    write_catalog(rows, root, output)
    print(f"{len(rows)} references: presenters and readings written")


if __name__ == "__main__":
    main()

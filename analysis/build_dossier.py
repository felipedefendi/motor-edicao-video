"""Builds the study documents of each reference from its transcript, metadata, scene cuts and a
hand-written analysis/dossier_config.json.

Usage: python analysis/build_dossier.py <root>

Writes, per reference, in analysis/:
  STRUCTURED_COPY.md        literal transcript split into hook / body / CTA
  DOSSIER.md                identification, narrative structure, visual reading, reusable pattern
  SCENE_BREAKDOWN.md        one row per detected scene with a link to its frame
  LOW_CONFIDENCE_WORDS.md   words the transcriber was unsure about
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def stamp(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{seconds - minutes * 60:05.2f}"


def exact_slice(segments: list[dict], start: float, end: float) -> str:
    selected = [s["text"].strip() for s in segments if s["start"] >= start - 0.02 and s["end"] <= end + 0.02]
    return " ".join(selected).strip()


def exact_phrase(full_text: str, requested: str) -> str:
    match = re.search(re.escape(requested), full_text, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Key quote is not literal: {requested!r}")
    return full_text[match.start(): match.end()]


def bullet_lines(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values) if values else "- Not identified"


def scene_description(scene: dict, blocks: list[dict]) -> str:
    midpoint = (float(scene["start_s"]) + float(scene["end_s"])) / 2
    for block in blocks:
        if float(block["start_s"]) <= midpoint < float(block["end_s"]):
            return block["description"]
    return "Visual change detected automatically; see the frame."


def generate(ref_dir: Path) -> None:
    config_path = ref_dir / "analysis" / "dossier_config.json"
    if not config_path.exists():
        return
    config = json.loads(config_path.read_text(encoding="utf-8"))
    whisper = json.loads((ref_dir / "transcript" / "whisper.json").read_text(encoding="utf-8"))
    metadata = json.loads((ref_dir / "analysis" / "metadata.json").read_text(encoding="utf-8"))
    scenes = json.loads((ref_dir / "analysis" / "scenes_auto.json").read_text(encoding="utf-8"))
    segments = whisper["segments"]
    full_text = whisper["text"].strip()
    duration = float(metadata["duration_s"])
    hook_end = float(config["hook_end_s"])
    cta_start = float(config["cta_start_s"])
    hook = exact_slice(segments, 0.0, hook_end)
    body = exact_slice(segments, hook_end, cta_start)
    cta = exact_slice(segments, cta_start, duration + 1.0)
    quotes = [exact_phrase(full_text, phrase) for phrase in config.get("key_quotes", [])]

    copy_doc = f"""# Structured copy — {config['id']} {config['name']}

> Literal Whisper transcript. No word was rewritten, corrected, summarised or added. See `../transcript/words.csv` for the timestamp and confidence of each word.

## HOOK — 00:00.00 to {stamp(hook_end)}

{hook}

## BODY — {stamp(hook_end)} to {stamp(cta_start)}

{body}

## CTA — {stamp(cta_start)} to {stamp(duration)}

{cta}

## Key quotes (literal)

{bullet_lines([f'“{p}”' for p in quotes])}

## Full text — literal

{full_text}
"""
    (ref_dir / "analysis" / "STRUCTURED_COPY.md").write_text(copy_doc, encoding="utf-8")

    dossier = f"""# {config['id']} — {config['name']}

## Identification

- Family/variation: {config.get('family', 'single piece')}
- File: `{metadata['original_file']}`
- Duration: {stamp(duration)}
- Resolution: {metadata['resolution']} · FPS: {metadata['fps']} · codec: {metadata['video_codec']}
- SHA-256: `{metadata['sha256']}`
- Scenes detected automatically: {len(scenes)}
- Short concept: {config['concept']}

## Narrative structure

- Hook: 00:00.00–{stamp(hook_end)} — {config['hook_summary']}
- Body: {stamp(hook_end)}–{stamp(cta_start)} — {config['body_summary']}
- CTA: {stamp(cta_start)}–{stamp(duration)} — {config['cta_summary']}

The full literal lines are in [STRUCTURED_COPY.md](STRUCTURED_COPY.md). The split does not change the text.

## Visual reading and editing

- Background/setting: {config['background']}
- Presenter: {config['presenter']}
- Hook visual: {config['hook_visual']}
- Body visual: {config['body_visual']}
- Captions and typography: {config['captions']}
- Colours: {config['colours']}
- Pacing and cuts: {config['pacing']}
- B-roll / visual proof: {config['broll']}
- Transitions/effects: {config['effects']}
- CTA visual: {config['cta_visual']}

## Key quotes — literal speech

{bullet_lines([f'“{p}”' for p in quotes])}

## Reusable pattern observed

{bullet_lines(config['reusable_pattern'])}

## Study material

- `../frames/overview.jpg`: overview at 20 points of the video.
- `../frames/timeline_5s/`: one frame every 5 seconds.
- `../scene_frames/`: first frame of each detected visual change.
- `scenes_auto.csv`: frame by frame per scene, with start, end and duration.
- `sampled_palette.json`: dominant colours along the timeline.
- `../transcript/segments.txt`: literal text with timestamps.
- `../transcript/words.csv`: text word by word with confidence.
- `../transcript/whisper.json`: full Whisper output.

## Reliability notes

{bullet_lines(config.get('notes', ['The text is raw; check low-confidence words in the CSV before reusing it.']))}
"""
    (ref_dir / "analysis" / "DOSSIER.md").write_text(dossier, encoding="utf-8")

    scene_rows = []
    blocks = config.get("visual_blocks", [])
    for scene in scenes:
        frame_link = "../" + scene["frame"].replace("\\", "/")
        scene_rows.append(
            f"| {scene['scene']:03d} | {stamp(float(scene['start_s']))} | {stamp(float(scene['end_s']))} | "
            f"{float(scene['duration_s']):.2f}s | [{Path(scene['frame']).name}]({frame_link}) | "
            f"{scene_description(scene, blocks)} |"
        )
    scene_doc = f"""# Scene breakdown — {config['id']} {config['name']}

> Boundaries were detected by visual change at 2 fps. Each row points to the first frame of the scene. The description names the matching visual block; confirm micro-cuts directly on the frames when needed.

| Scene | Start | End | Duration | Frame | Visual description |
|---:|---:|---:|---:|---|---|
{chr(10).join(scene_rows)}

## Main visual blocks

{bullet_lines([f"{stamp(float(b['start_s']))}–{stamp(float(b['end_s']))}: {b['description']}" for b in blocks])}
"""
    (ref_dir / "analysis" / "SCENE_BREAKDOWN.md").write_text(scene_doc, encoding="utf-8")

    uncertain = []
    for segment in segments:
        for word in segment.get("words", []):
            probability = float(word.get("probability", 0.0))
            if probability < 0.60:
                uncertain.append(
                    f"| {stamp(float(word['start']))} | {stamp(float(word['end']))} | "
                    f"`{word['word']}` | {probability:.3f} | {segment['text'].strip()} |"
                )
    uncertain_doc = f"""# Low-confidence words — {config['id']} {config['name']}

> Automatic list of words with Whisper confidence below 0.60. The text was not corrected; this file shows where a person should check the original audio.

| Start | End | Literal word | Confidence | Literal segment context |
|---:|---:|---|---:|---|
{chr(10).join(uncertain) if uncertain else '| — | — | — | — | No word below the threshold. |'}
"""
    (ref_dir / "analysis" / "LOW_CONFIDENCE_WORDS.md").write_text(uncertain_doc, encoding="utf-8")
    print(f"{ref_dir.name}: dossier written")


def main() -> None:
    root = Path(sys.argv[1])
    for config_path in sorted(root.rglob("analysis/dossier_config.json")):
        generate(config_path.parent.parent)


if __name__ == "__main__":
    main()

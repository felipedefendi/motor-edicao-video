"""Transcribes reference videos with Whisper (word timestamps) and writes text, SRT, segment and word files.

Usage: python analysis/transcribe.py <root> <id> [<id> ...] [--model medium] [--language en]

<root> holds one folder per reference, each with original/*.mp4 and, optionally,
analysis/dossier_config.json carrying an "id". Output goes to <reference>/transcript/.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import torch
import whisper


def find_reference(root: Path, ref_id: str) -> Path:
    for video in root.rglob("original/*.mp4"):
        ref_dir = video.parent.parent
        config = ref_dir / "analysis" / "dossier_config.json"
        if config.exists() and json.loads(config.read_text(encoding="utf-8")).get("id") == ref_id:
            return ref_dir
        if ref_dir.name == ref_id or ref_dir.name.startswith(ref_id + "_"):
            return ref_dir
    raise FileNotFoundError(f"Reference not found: {ref_id}")


def ts(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    h, millis = divmod(millis, 3_600_000)
    m, millis = divmod(millis, 60_000)
    s, ms = divmod(millis, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe_ids(root: Path, ids: list[str], model_name: str, language: str) -> None:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisper.load_model(model_name, device=device)
    for ref_id in ids:
        ref_dir = find_reference(root, ref_id)
        video = next((ref_dir / "original").glob("*.mp4"))
        out = ref_dir / "transcript"
        out.mkdir(parents=True, exist_ok=True)
        if (out / "whisper.json").exists():
            print(f"{ref_id}: already transcribed")
            continue
        print(f"{ref_id}: transcribing {video.name}", flush=True)
        result = model.transcribe(
            str(video),
            language=language,
            word_timestamps=True,
            fp16=device == "cuda",
            verbose=False,
            condition_on_previous_text=True,
        )
        (out / "whisper.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "text.txt").write_text(result["text"].strip() + "\n", encoding="utf-8")
        with (out / "segments.txt").open("w", encoding="utf-8") as handle:
            for segment in result["segments"]:
                handle.write(f"[{ts(segment['start'])} --> {ts(segment['end'])}] {segment['text'].strip()}\n")
        with (out / "captions.srt").open("w", encoding="utf-8") as handle:
            for i, segment in enumerate(result["segments"], 1):
                handle.write(f"{i}\n{ts(segment['start'])} --> {ts(segment['end'])}\n{segment['text'].strip()}\n\n")
        with (out / "words.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=["segment", "start_s", "end_s", "word", "probability"])
            writer.writeheader()
            for segment in result["segments"]:
                for word in segment.get("words", []):
                    writer.writerow({
                        "segment": segment["id"],
                        "start_s": round(word["start"], 3),
                        "end_s": round(word["end"], 3),
                        "word": word["word"],
                        "probability": round(word.get("probability", 0.0), 5),
                    })
        print(f"{ref_id}: done", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("ids", nargs="+")
    parser.add_argument("--model", default="medium")
    parser.add_argument("--language", default="en")
    args = parser.parse_args()
    transcribe_ids(Path(args.root), args.ids, args.model, args.language)


if __name__ == "__main__":
    main()

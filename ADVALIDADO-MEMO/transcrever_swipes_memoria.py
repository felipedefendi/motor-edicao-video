from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import torch
import whisper


ROOT = Path(r"G:\Meu Drive\ADVALIDADO-MEMO\Ads Swipe Memoria")


def find_ad(ad_id: str) -> Path:
    for video in ROOT.rglob("original/*.mp4"):
        ad_dir = video.parent.parent
        config = ad_dir / "analise" / "config_dossie.json"
        if config.exists() and json.loads(config.read_text(encoding="utf-8")).get("id") == ad_id:
            return ad_dir
        if ad_dir.name == ad_id or ad_dir.name.startswith(ad_id + "_"):
            return ad_dir
    raise FileNotFoundError(f"Swipe não encontrado: {ad_id}")


def ts(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    h, millis = divmod(millis, 3_600_000)
    m, millis = divmod(millis, 60_000)
    s, ms = divmod(millis, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe_ids(ids: list[str], model_name: str) -> None:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = whisper.load_model(model_name, device=device)
    for ad_id in ids:
        ad_dir = find_ad(ad_id)
        video = next((ad_dir / "original").glob("*.mp4"))
        out = ad_dir / "transcricao"
        out.mkdir(parents=True, exist_ok=True)
        if (out / "whisper.json").exists():
            print(f"{ad_id}: já transcrito")
            continue
        print(f"{ad_id}: transcrevendo {video.name}", flush=True)
        result = model.transcribe(
            str(video),
            language="en",
            word_timestamps=True,
            fp16=device == "cuda",
            verbose=False,
            condition_on_previous_text=True,
        )
        (out / "whisper.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "copy.txt").write_text(result["text"].strip() + "\n", encoding="utf-8")
        with (out / "segmentos.txt").open("w", encoding="utf-8") as handle:
            for segment in result["segments"]:
                handle.write(f"[{ts(segment['start'])} --> {ts(segment['end'])}] {segment['text'].strip()}\n")
        with (out / "legendas.srt").open("w", encoding="utf-8") as handle:
            for i, segment in enumerate(result["segments"], 1):
                handle.write(f"{i}\n{ts(segment['start'])} --> {ts(segment['end'])}\n{segment['text'].strip()}\n\n")
        with (out / "palavras.csv").open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=["segmento", "inicio_s", "fim_s", "palavra", "probabilidade"])
            writer.writeheader()
            for segment in result["segments"]:
                for word in segment.get("words", []):
                    writer.writerow({
                        "segmento": segment["id"],
                        "inicio_s": round(word["start"], 3),
                        "fim_s": round(word["end"], 3),
                        "palavra": word["word"],
                        "probabilidade": round(word.get("probability", 0.0), 5),
                    })
        print(f"{ad_id}: concluído", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ids", nargs="+")
    parser.add_argument("--model", default="medium")
    args = parser.parse_args()
    transcribe_ids(args.ids, args.model)


if __name__ == "__main__":
    main()

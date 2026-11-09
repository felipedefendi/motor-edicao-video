"""Assembles a long video from lossless H.264 segments and copies the original audio once.

Each window uses integer frame bounds [start, end). A per-recipe cache lets the job resume.
Usage: python longform/assemble_lossless.py jobs/<job> [--output master.mp4]
"""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import subprocess
import sys

FPS = 30
FRAME = (1080, 1920)
COLOR = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"


def probe(p):
    return json.loads(subprocess.check_output(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,r_frame_rate,nb_frames,start_time", "-of", "json", str(p)]))["streams"][0]


def main():
    job = Path(sys.argv[1]).resolve()
    name = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else "master.mp4"
    src = job / "input/original.mp4"
    v = probe(src)
    assert v["r_frame_rate"] == f"{FPS}/1" and (v["width"], v["height"]) == FRAME, \
        f"This assembler requires the {FRAME[0]}x{FRAME[1]}/{FPS}fps contract"
    total = int(v["nb_frames"])
    windows = json.loads((job / "docs/windows.json").read_text(encoding="utf-8-sig"))
    windows.sort(key=lambda x: x.get("start_frame", round(x["start"] * FPS)))

    segments, cursor = [], 0
    for w in windows:
        a = w.get("start_frame", round(w["start"] * FPS))
        b = w.get("end_frame_exclusive", round(w["end"] * FPS))
        assert cursor <= a < b <= total, f"Invalid or overlapping window: {w}"
        assert w.get("clip"), f"Window without clip: {w}"
        if cursor < a:
            segments.append({"type": "original", "start": cursor, "n": a - cursor, "source": str(src), "offset": cursor})
        clip = (job / w["clip"]).resolve()
        cv = probe(clip)
        off = round(w.get("clip_start", 0) * FPS)
        assert cv["r_frame_rate"] == f"{FPS}/1" and (cv["width"], cv["height"]) == FRAME, f"Clip contract: {clip}"
        assert int(cv["nb_frames"]) >= off + b - a, f"Clip too short: {clip}"
        segments.append({"type": "replace", "window": w["segment"], "start": a, "n": b - a, "source": str(clip), "offset": off})
        cursor = b
    if cursor < total:
        segments.append({"type": "original", "start": cursor, "n": total - cursor, "source": str(src), "offset": cursor})
    assert sum(s["n"] for s in segments) == total

    work = job / "work/lossless_segments"
    work.mkdir(parents=True, exist_ok=True)
    out_dir = job / "output"
    out_dir.mkdir(exist_ok=True)
    history = out_dir / "_history"
    history.mkdir(exist_ok=True)
    for i, s in enumerate(segments):
        s["id"] = i
        s["file"] = str(work / f"s{i:04d}.mp4")
    (job / "docs/assembly_segments.json").write_text(json.dumps(segments, indent=2), encoding="utf-8")

    def encode(s):
        inp, dst = Path(s["source"]), Path(s["file"])
        meta = dst.with_suffix(".json")
        stat = inp.stat()
        recipe = {**s, "source_size": stat.st_size, "source_mtime": stat.st_mtime_ns, "codec": "x264_qp0_fast_bf0_v1"}
        key = hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()
        if dst.exists() and meta.exists():
            old = json.loads(meta.read_text())
            if old.get("recipe_sha256") == key and int(probe(dst).get("nb_frames", -1)) == s["n"]:
                return f"cache {s['id']:04d}: {s['n']} frames"
        seek, rem = s["offset"] // FPS, s["offset"] % FPS
        tmp = dst.with_suffix(".partial.mp4")
        vf = (f"trim=start_frame={rem}:end_frame={rem + s['n']},setpts=PTS-STARTPTS,{COLOR},format=yuv420p")
        args = ["ffmpeg", "-v", "error", "-y", "-threads", "2", "-ss", str(seek), "-i", str(inp), "-vf", vf,
                "-frames:v", str(s["n"]), "-an", "-c:v", "libx264", "-threads", "2", "-preset", "fast",
                "-crf", "0", "-bf", "0", "-r", str(FPS), "-video_track_timescale", "15360", str(tmp)]
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"Segment {s['id']}: {r.stderr[-3000:]}")
        assert int(probe(tmp)["nb_frames"]) == s["n"], f"Frame count of segment {s['id']}"
        tmp.replace(dst)
        meta.write_text(json.dumps({"recipe_sha256": key, "recipe": recipe}, indent=2))
        return f"done {s['id']:04d}: {s['type']} {s['n']} frames"

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        for r in ex.map(encode, segments):
            print(r, flush=True)

    concat_list = work / "concat.txt"
    concat_list.write_text("".join("file '" + Path(s["file"]).name + "'\n" for s in segments), encoding="utf-8")
    dst = out_dir / name
    if dst.exists():
        i = 1
        while (history / f"{i:02d}_{name}").exists():
            i += 1
        dst.replace(history / f"{i:02d}_{name}")
    tmp = out_dir / (dst.stem + ".partial.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-i", str(src),
                    "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-map_metadata", "1", "-movflags", "+faststart", str(tmp)],
                   check=True)
    assert int(probe(tmp)["nb_frames"]) == total, "Final frame count diverged"
    tmp.replace(dst)
    print(f"MASTER DONE: {dst}; {total} frames. Run the strict audit and a visual check.", flush=True)


if __name__ == "__main__":
    main()

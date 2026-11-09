r"""Frame scan of a long video: numbered contact sheets + time index, for a person to review and mark
where the object to be replaced appears.

Usage:  python longform/scan_frames.py jobs/<job> [fps]

Writes to jobs/<job>/work/scan/:
  sheet_000.png, sheet_001.png ...   6x4 tiles, 24 frames per sheet
  index.json                         sheet -> tile position -> frame timestamp
And writes jobs/<job>/docs/technical_contract.json with what the final render must respect.

Decides nothing: marking where the object appears is done by a person looking at the sheets.
Does not use drawtext (no fontconfig required): numbering is by tile position, read from index.json.
"""
import json
import os
import subprocess
import sys

COLS, ROWS = 6, 4
PER_SHEET = COLS * ROWS
TILE_W = 240


def run(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(f"failed: {' '.join(args[:3])}...\n{p.stderr[-2000:]}")
    return p.stdout


def contract(src, out):
    v = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames,pix_fmt",
                        "-of", "json", src]))["streams"][0]
    a = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "stream=codec_name,sample_rate,channels,bit_rate", "-of", "json", src]))
    f = json.loads(run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
                        "-of", "json", src]))["format"]
    c = {"source": os.path.abspath(src), "video": v,
         "audio": a["streams"][0] if a.get("streams") else None, "format": f}
    c["vfr_suspected"] = v.get("r_frame_rate") != v.get("avg_frame_rate")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(c, fh, indent=2, ensure_ascii=False)
    return c


def main():
    job = sys.argv[1].rstrip("\\/")
    fps = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    inp = os.path.join(job, "input")
    videos = [f for f in sorted(os.listdir(inp)) if f.lower().endswith((".mp4", ".mov", ".mkv"))]
    if not videos:
        raise SystemExit(f"no video in {inp}")
    src = os.path.join(inp, videos[0])
    work = os.path.join(job, "work", "scan")
    docs = os.path.join(job, "docs")
    os.makedirs(work, exist_ok=True)
    os.makedirs(docs, exist_ok=True)

    c = contract(src, os.path.join(docs, "technical_contract.json"))
    duration = float(c["format"]["duration"])
    print(f"input: {videos[0]}  {c['video']['width']}x{c['video']['height']}  "
          f"{c['video'].get('r_frame_rate')} fps  {duration:.2f}s")
    if c["vfr_suspected"]:
        print("WARNING: r_frame_rate != avg_frame_rate -> the source may be variable frame rate.")
    if c["video"]["width"] > c["video"]["height"]:
        print("WARNING: landscape video. This pipeline assumes 9:16 -> stop and confirm before continuing.")

    sheets = int(duration * fps // PER_SHEET) + 1
    run(["ffmpeg", "-v", "error", "-y", "-i", src,
         "-vf", f"fps={fps},scale={TILE_W}:-2,tile={COLS}x{ROWS}:padding=4:color=0x202020",
         "-frames:v", str(sheets), "-start_number", "0",
         os.path.join(work, "sheet_%03d.png")])

    index, n = [], 0
    for s in range(sheets):
        name = f"sheet_{s:03d}.png"
        if not os.path.exists(os.path.join(work, name)):
            break
        tiles = []
        for r in range(ROWS):
            for col in range(COLS):
                t = n / fps
                if t <= duration:
                    tiles.append({"pos": f"R{r + 1}C{col + 1}", "t": round(t, 3),
                                  "mmss": f"{int(t) // 60:02d}:{t % 60:06.3f}"})
                n += 1
        index.append({"sheet": name, "frames": tiles})
    with open(os.path.join(work, "index.json"), "w", encoding="utf-8") as fh:
        json.dump({"sample_fps": fps, "columns": COLS, "rows": ROWS,
                   "duration_s": duration, "sheets": index}, fh, indent=2, ensure_ascii=False)
    print(f"{len(index)} sheets in {work}")
    print("Next: review each sheet, mark where the object appears and build the segment sheet.")


if __name__ == "__main__":
    main()

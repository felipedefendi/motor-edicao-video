"""Builds an audition reel of a sound-effect library: one 2.6 s card per sample with its category and number.

Usage: python assembly/demos/sfx_audition.py <sfx_dir> <output.mp4>
<sfx_dir> holds one subfolder per category with .mp3 files named <category>_<number>_*.mp3.
"""
import glob
import os
import subprocess
import sys

SRC, DST = sys.argv[1], sys.argv[2]
TMP = os.path.join(os.path.dirname(os.path.abspath(DST)), "_audition")
FONT = "C\\:/Windows/Fonts/arialbd.ttf"
ORDER = ["whoosh", "swipe", "pop", "click", "chime", "money", "impact", "bass", "sub", "riser"]
SEG = 2.6

os.makedirs(TMP, exist_ok=True)
segments = []
for cat in ORDER:
    for f in sorted(glob.glob(os.path.join(SRC, cat, "*.mp3"))):
        name = os.path.basename(f)
        num = name.split("_")[1]
        label = f"{cat.upper()} {num}"
        out = os.path.join(TMP, f"{cat}_{num}.mp4")
        subprocess.run(["ffmpeg", "-v", "error", "-y",
                        "-f", "lavfi", "-i", f"color=c=0x101014:s=720x1280:r=30:d={SEG}",
                        "-i", f,
                        "-filter_complex",
                        f"[0:v]drawtext=fontfile='{FONT}':text='{label}':fontcolor=white:fontsize=96:x=(w-tw)/2:y=(h-th)/2,"
                        f"drawtext=fontfile='{FONT}':text='{cat}':fontcolor=0x888888:fontsize=34:x=(w-tw)/2:y=h/2+90[v];"
                        f"[1:a]atrim=0:{SEG - 0.4},afade=t=out:st={SEG - 0.7}:d=0.3,loudnorm=I=-16:TP=-1.5,"
                        f"aresample=48000,adelay=250|250,apad=whole_dur={SEG},aformat=channel_layouts=stereo[a]",
                        "-map", "[v]", "-map", "[a]", "-t", str(SEG), "-c:v", "libx264", "-preset", "veryfast",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out], check=True)
        segments.append(out)

concat_list = os.path.join(TMP, "list.txt")
with open(concat_list, "w") as fh:
    fh.writelines(f"file '{s}'\n" for s in segments)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", DST], check=True)
print(len(segments), DST)

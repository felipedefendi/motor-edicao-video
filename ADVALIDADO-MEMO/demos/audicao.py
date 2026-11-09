import os, glob, subprocess, sys

SRC = r"G:\Meu Drive\ADVALIDADO-MEMO\biblioteca\sfx\pixabay"
OUT = r"G:\Meu Drive\ADVALIDADO-MEMO\jobs\ad01\work\v7_estilos"
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aud")
FONT = "C\\:/Windows/Fonts/arialbd.ttf"
ORDER = ["whoosh", "swipe", "pop", "click", "chime", "money", "impact", "bass", "sub", "riser"]
SEG = 2.6

os.makedirs(TMP, exist_ok=True)
segs = []
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
        segs.append(out)

lst = os.path.join(TMP, "lista.txt")
with open(lst, "w") as fh:
    fh.writelines(f"file '{s}'\n" for s in segs)
dst = os.path.join(OUT, "AUDICAO_SFX_pixabay.mp4")
subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", dst], check=True)
print(len(segs), dst)

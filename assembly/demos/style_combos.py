"""Renders three complete style combos (typography + sound design + flashes) over the same 8-second take,
so a direction can be picked by comparing finished videos.

Usage: python assembly/demos/style_combos.py <library_dir> <take.mp4> <output_dir>
<library_dir> must hold fonts/, sfx/<category>/*.mp3 and broll/. The word timings and phrases below are
an example; adapt WORDS, B_ROLLS and the combos to the take being compared.
"""
import os
import re
import shutil
import subprocess
import sys

LIB, TAKE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
FONTS = os.path.join(LIB, "fonts")
SFX = os.path.join(LIB, "sfx")
BR = os.path.join(LIB, "broll")
TMP = os.path.join(OUT, "_combos")
os.makedirs(TMP, exist_ok=True)
COLOR = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"
DUR = 8.2
SPLIT = (2.24, 7.9)
# (file, from, to, source offset, vertical anchor)
B_ROLLS = [("people/b1.mp4", 2.24, 3.54, 7.2, 0.45),
           ("detail/b2.mp4", 3.54, 5.40, 2.4, 0.5),
           ("people/b3.mp4", 5.40, 7.90, 1.0, 0.40)]

# word -> start time (s) in the take; example values
WORDS = {"I": 0.0, "changed": 0.32, "one": 0.54, "thing": 0.98, "about": 1.32, "my": 1.64, "day": 2.24,
         "and": 2.70, "my": 3.00, "mornings": 3.26, "changed": 3.54, "in": 4.18, "two": 4.44, "weeks": 4.66,
         "If": 5.44, "you": 5.54, "work": 5.78, "home": 6.04, "you2": 6.56, "need": 6.68, "to": 6.88, "see": 7.08,
         "this": 7.28}


def bgr(h):
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def T(t):
    t = max(0, t)
    return f"0:00:{int(t):02d}.{int(round((t % 1) * 100)):02d}"


HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: H,Arial,80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def event(a, b, x, y, tags, txt, layer=1):
    return f"Dialogue: {layer},{T(a)},{T(b)},H,,0,0,0,,{{\\an5\\pos({x},{y}){tags}}}{txt}\n"


POP = "\\fscx112\\fscy112\\t(0,110,\\fscx100\\fscy100)"


# ---------- COMBO 1: giant condensed headline only, white + lime, no running caption
def combo1():
    f = "\\fnLeague Gothic\\b0"
    sh = "\\bord0\\shad0\\blur0"
    halo = "\\bord14\\blur16\\3c&H000000&\\3a&H70&\\1a&HFF&"
    LIME, WH = bgr("D4FF1E"), bgr("FFFFFF")
    e = []

    def word(a, b, x, y, fs, col, txt):
        e.append(event(a, b, x, y, f"{f}\\fs{fs}{halo}", txt, 0))
        e.append(event(a, b, x, y, f"{f}\\fs{fs}\\1c{col}{sh}{POP}", txt, 1))
    end1 = 5.3
    word(WORDS["my"], end1, 190, 560, 150, WH, "MY")
    word(WORDS["mornings"], end1, 360, 560, 150, WH, "MORNINGS")
    word(WORDS["changed"], end1, 360, 700, 175, LIME, "CHANGED")
    word(WORDS["in"], end1, 360, 815, 96, WH, "IN TWO WEEKS")
    end2 = DUR
    word(WORDS["work"], end2, 360, 600, 230, LIME, "WORK FROM HOME?")
    word(WORDS["you2"], end2, 360, 770, 92, WH, "YOU NEED TO SEE THIS")
    sfx = [("looming/looming_02.mp3", 0.0, 2.6, -16),
           ("flash/flash_02.mp3", WORDS["my"] - 0.03, 0.8, -12),
           ("clock/clock_03.mp3", WORDS["in"], 1.0, -16),
           ("flash/flash_02.mp3", WORDS["work"] - 0.03, 0.8, -12)]
    flashes = [WORDS["my"], WORDS["work"]]
    return "Condensed", ["LeagueGothic.ttf"], e, sfx, flashes


# ---------- COMBO 2: bold white with glow + keyword in script, word by word
def combo2():
    B = "\\fnPlus Jakarta Sans\\b1"
    S = "\\fnGreat Vibes\\b0"
    glow = "\\bord6\\blur10\\3c&HFFFFFF&\\3a&HC8&"
    e = []
    halo = "\\bord16\\blur18\\3c&H000000&\\3a&H60&\\1a&HFF&"

    def w(a, b, x, y, fs, font, txt, col="&H00FFFFFF&"):
        e.append(event(a, b, x, y, f"{font}\\fs{fs}{halo}", txt, 0))
        e.append(event(a, b, x, y, f"{font}\\fs{fs}\\1c{col}{glow}{POP}", txt, 1))
    w(WORDS["my"], WORDS["changed"], 360, 560, 62, B, "my")
    w(WORDS["mornings"], WORDS["changed"], 360, 660, 175, S, "mornings")
    w(WORDS["changed"], WORDS["If"], 360, 600, 68, B, "changed")
    w(WORDS["in"], WORDS["If"], 360, 690, 62, B, "in")
    w(WORDS["two"], WORDS["If"], 360, 790, 165, S, "two weeks.")
    w(WORDS["If"], WORDS["work"], 360, 600, 62, B, "if you")
    w(WORDS["work"], WORDS["you2"], 360, 650, 200, S, "work from home", bgr("FFE6A0"))
    w(WORDS["you2"], DUR, 360, 600, 62, B, "you need to")
    w(WORDS["see"], DUR, 360, 710, 175, S, "see this.")
    sfx = [("riser_metal/riser_metal_02.mp3", 0.6, 1.7, -18),
           ("flash/flash_03.mp3", SPLIT[0] - 0.04, 0.8, -14),
           ("sword/sword_02.mp3", WORDS["changed"], 0.9, -20),
           ("clock/clock_03.mp3", WORDS["in"], 1.0, -18),
           ("tvnoise/tvnoise_03.mp3", 5.36, 0.35, -22)]
    flashes = [SPLIT[0]]
    return "Script", ["PlusJakartaSans-ExtraBold.ttf", "GreatVibes.ttf"], e, sfx, flashes


# ---------- COMBO 3: hybrid (kinetic structure + Anton + punchy palette)
def combo3():
    f = "\\fnAnton\\b0"
    st = "\\bord6\\3c&H000000&\\shad4\\4c&H000000&\\4a&H40&"
    WH, R_, LIME, Y = bgr("FFFFFF"), bgr("FF2B2B"), bgr("C6FF1A"), bgr("FFE11A")
    e = []

    def w(a, b, x, y, fs, col, txt):
        e.append(event(a, b, x, y, f"{f}\\fs{fs}\\1c{col}{st}{POP}", txt, 1))
    end1 = 5.3
    w(WORDS["my"], end1, 165, 560, 120, WH, "MY")
    w(WORDS["mornings"], end1, 420, 560, 120, R_, "MORNINGS")
    w(WORDS["changed"], end1, 360, 680, 128, LIME, "CHANGED")
    w(WORDS["in"], end1, 360, 795, 104, WH, "IN TWO WEEKS")
    w(WORDS["If"], DUR, 360, 520, 100, WH, "IF YOU")
    w(WORDS["work"], DUR, 360, 640, 150, Y, "WORK FROM HOME")
    w(WORDS["you2"], DUR, 360, 760, 100, WH, "YOU NEED")
    w(WORDS["to"], DUR, 360, 865, 100, WH, "TO SEE THIS")
    sfx = [("sub/sub_03.mp3", 0.0, 1.8, -12),
           ("whoosh/whoosh_03.mp3", SPLIT[0] - 0.12, 0.9, -16),
           ("flash/flash_02.mp3", WORDS["my"] - 0.03, 0.8, -15),
           ("clock/clock_03.mp3", WORDS["in"], 1.0, -18),
           ("whoosh/whoosh_03.mp3", 5.30, 0.9, -16)]
    return "Hybrid", ["Anton.ttf"], e, sfx, []


def peak(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    return float(re.search(r"max_volume: ([-\d.]+) dB", r.stderr).group(1))


def render(name, fonts, events, sfx, flashes, idx):
    fd = os.path.join(TMP, f"fd_{name}")
    os.makedirs(fd, exist_ok=True)
    for fn in fonts:
        shutil.copy(os.path.join(FONTS, fn), fd)
    ass = f"{name}.ass"
    open(os.path.join(TMP, ass), "w", encoding="utf-8").write(HEADER + "".join(events))
    inputs = ["-i", TAKE]
    for p, a, b, ss, anc in B_ROLLS:
        inputs += ["-ss", str(ss), "-i", os.path.join(BR, p)]
    for p, t, d, db in sfx:
        inputs += ["-i", os.path.join(SFX, p)]
    a0, b0 = SPLIT
    fc = [f"[0:v]{COLOR},scale=720:-2,crop=720:1280,setsar=1,trim=0:{DUR},setpts=PTS-STARTPTS[base]",
          f"[0:v]{COLOR},scale=806:-2,crop=720:640:43:90,setsar=1,trim=0:{DUR},setpts=PTS-STARTPTS[top]",
          f"[base][top]overlay=0:0:enable='between(t,{a0},{b0})'[v0]"]
    last = "v0"
    for k, (p, a, b, ss, anc) in enumerate(B_ROLLS):
        fc.append(f"[{k + 1}:v]{COLOR},scale=720:640:force_original_aspect_ratio=increase,crop=720:640:(iw-720)*{anc}:(ih-640)/2,setsar=1,"
                  f"trim=0:{b - a + 0.1},setpts=PTS-STARTPTS+{a}/TB[b{k}]")
        fc.append(f"[{last}][b{k}]overlay=0:640:eof_action=pass:enable='between(t,{a},{b})'[v{k + 1}]")
        last = f"v{k + 1}"
    boxes = ",".join(f"drawbox=color=white@0.85:t=fill:enable='between(t,{t:.3f},{t + 0.067:.3f})',"
                     f"drawbox=color=0xFFD9A0@0.4:t=fill:enable='between(t,{t + 0.067:.3f},{t + 0.15:.3f})'"
                     for t in flashes)
    fc.append(f"[{last}]{boxes + ',' if boxes else ''}ass={ass}:fontsdir=fd_{name}[vout]")
    mix = ["[0:a]atrim=0:{0},asetpts=PTS-STARTPTS[voice]".format(DUR)]
    labels = ["[voice]"]
    for k, (p, t, d, db) in enumerate(sfx):
        g = db - peak(os.path.join(SFX, p))
        i = 1 + len(B_ROLLS) + k
        ms = int(t * 1000)
        mix.append(f"[{i}:a]atrim=0:{d},afade=t=out:st={max(0, d - 0.25)}:d=0.25,volume={g:.1f}dB,"
                   f"aresample=48000,aformat=channel_layouts=stereo,adelay={ms}|{ms}[s{k}]")
        labels.append(f"[s{k}]")
    mix.append("[voice]aresample=48000,aformat=channel_layouts=stereo[vv]")
    labels[0] = "[vv]"
    mix.append(f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0:duration=first,loudnorm=I=-14:TP=-1.5,"
               f"aresample=48000[aout]")
    out = os.path.join(OUT, f"COMBO_{idx}_{name}.mp4")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(fc + mix),
                    "-map", "[vout]", "-map", "[aout]", "-t", str(DUR), "-r", "30", "-c:v", "libx264",
                    "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out],
                   check=True, cwd=TMP)
    return out


if __name__ == "__main__":
    for i, fn in enumerate([combo1, combo2, combo3], 1):
        print(render(*fn(), i))

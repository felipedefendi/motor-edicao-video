"""Typography style sheet: renders the same sample lines over clean frames with six font + palette presets
and stacks them side by side, so a style can be picked by looking.

Usage: python assembly/demos/style_sheet.py <fonts_dir> <work_dir>
<work_dir> must hold the clean frames named in MOMENTS (f1.png, f2.png, body3.png). Writes SHEET_<moment>.jpg there.
"""
import os
import shutil
import subprocess
import sys

FONTS = sys.argv[1]
HERE = os.path.abspath(sys.argv[2])


def bgr(hexrgb):
    r, g, b = hexrgb[0:2], hexrgb[2:4], hexrgb[4:6]
    return f"&H00{b}{g}{r}&".upper()


VIVID = {"W": "FFFFFF", "R": "FF2B2B", "G": "00E35B", "Y": "FFE11A"}
NEON = {"W": "FFFFFF", "R": "FF1744", "G": "39FF14", "Y": "FAFF00"}
PREMIUM = {"W": "FFF8EC", "R": "EF4444", "G": "22C55E", "Y": "FFC400"}

# (label, file, family, average upper-case width / font size, line pitch / font size, palette, outline)
PRESETS = [
    ("1 ANTON + VIVID", "Anton.ttf", "Anton", 0.275, 0.80, VIVID, "stroke"),
    ("2 MONTSERRAT BLACK + VIVID", "Montserrat-Black.ttf", "Montserrat Black", 0.54, 0.92, VIVID, "stroke"),
    ("3 BEBAS NEUE + NEON", "BebasNeue.ttf", "Bebas Neue", 0.285, 0.84, NEON, "stroke"),
    ("4 ARCHIVO BLACK + PREMIUM", "ArchivoBlack.ttf", "Archivo Black", 0.49, 0.92, PREMIUM, "glow"),
    ("5 POPPINS BLACK + VIVID", "Poppins-Black.ttf", "Poppins Black", 0.34, 0.92, VIVID, "stroke"),
    ("6 BARLOW COND. + NEON", "BarlowCondensed-Black.ttf", "Barlow Condensed Black", 0.33, 0.84, NEON, "stroke"),
]

# each moment: clean frame + lines [(words with colour), ...] + centre y + max width
MOMENTS = {
    "m1_0004": ("f1.png", [[("MY", "W"), ("MORNINGS", "R")], [("CHANGED", "G")], [("IN TWO WEEKS", "W")]], 640, 600),
    "m2_0007": ("f2.png", [[("IF YOU", "W")], [("WORK FROM HOME", "Y")], [("YOU NEED", "W")], [("TO SEE THIS", "W")]], 640, 600),
    "m3_0102": ("body3.png", [[("IT COSTS LESS THAN", "W")], [("$5", "G")]], 520, 620),
}

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


def event(layer, x, y, tags, txt):
    return f"Dialogue: {layer},0:00:00.00,0:00:05.00,H,,0,0,0,,{{\\an5\\pos({x},{y}){tags}}}{txt}\n"


def build(preset, lines, cy, max_w):
    label, _, family, char_w, pitch, palette, look = preset
    nchar = max(len("".join(w for w, _ in ln)) + len(ln) - 1 for ln in lines)
    out, sizes = [], []
    for ln in lines:
        n = len("".join(w for w, _ in ln)) + len(ln) - 1
        fs = min(max_w / (n * char_w), max_w / (nchar * char_w) * 1.0)
        if len(lines) == 2 and n <= 3:          # a short number alone: giant
            fs = max_w / (nchar * char_w) * 2.3
        sizes.append(fs)
    total = sum(s * pitch for s in sizes)
    y = cy - total / 2
    for ln, fs in zip(lines, sizes):
        yc = y + fs * pitch / 2
        y += fs * pitch
        txt = " ".join(f"{{\\1c{bgr(palette[c])}}}{w}" for w, c in ln)
        base = f"\\fn{family}\\b1\\fs{fs:.0f}"
        if look == "stroke":
            out.append(event(1, 360, yc, f"{base}\\bord{fs * 0.075:.1f}\\3c&H000000&\\shad{fs * 0.05:.1f}\\4c&H000000&\\4a&H40&", txt))
        else:
            out.append(event(0, 360, yc, f"{base}\\bord{fs * 0.12:.1f}\\blur{fs * 0.18:.1f}\\3c&H000000&\\3a&H50&\\1a&HFF&", txt))
            out.append(event(1, 360, yc, f"{base}\\bord0\\shad{fs * 0.04:.1f}\\4c&H000000&\\4a&H50&", txt))
    return HEADER + "".join(out)


def run():
    os.chdir(HERE)
    for key, (png, lines, cy, max_w) in MOMENTS.items():
        cells = []
        for i, p in enumerate(PRESETS):
            d = os.path.join(HERE, "fd", str(i))
            os.makedirs(d, exist_ok=True)
            shutil.copy(os.path.join(FONTS, p[1]), d)
            ass = f"{key}_{i}.ass"
            open(ass, "w", encoding="utf-8").write(build(p, lines, cy, max_w))
            out = f"{key}_{i}.png"
            label = p[0].replace(":", "\\:")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", png, "-vf",
                            f"ass={ass}:fontsdir=fd/{i},scale=360:640,"
                            f"drawbox=y=0:w=iw:h=34:color=black@0.75:t=fill,"
                            f"drawtext=fontfile='C\\:/Windows/Fonts/arialbd.ttf':text='{label}':fontcolor=white:fontsize=17:x=8:y=9",
                            "-frames:v", "1", out], check=True)
            cells.append(out)
        args = sum([["-i", c] for c in cells], [])
        subprocess.run(["ffmpeg", "-v", "error", "-y", *args, "-filter_complex",
                        f"{''.join(f'[{k}]' for k in range(len(cells)))}hstack={len(cells)}",
                        "-q:v", "3", f"SHEET_{key}.jpg"], check=True)


if __name__ == "__main__":
    run()

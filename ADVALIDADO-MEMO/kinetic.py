"""Tipografia cinetica palavra a palavra para as frases de impacto (v6).

Cada palavra e um evento ASS proprio, posicionado com medida real da fonte (Pillow, calibrado contra o libass),
entrando no instante em que e falada: sobe 28px + escala 86%->100% + fade em ~180ms. Preenchimento solido,
reto, halo escuro so por tras. Opcional: icone colorido (emoji Fluent do Windows) que entra com pop.
"""
import os
import re

from PIL import Image, ImageDraw, ImageFont

FONT_FILE = r"C:\Windows\Fonts\bahnschrift.ttf"
EMOJI_FILE = r"C:\Windows\Fonts\seguiemj.ttf"
FONT_NAME, SCALEX = "Bahnschrift", 80
CAL = 0.825            # libass desenha ~82.5% da largura medida pelo Pillow (calibrado)
CAP_H = 0.61           # altura da maiuscula = 0.61 * fs
LINE_H = 0.80          # entrelinha = 0.80 * fs (blocos condensados, como na referencia)
_fonts = {}


def _font(size):
    if size not in _fonts:
        f = ImageFont.truetype(FONT_FILE, size)
        f.set_variation_by_name("Bold")
        _fonts[size] = f
    return _fonts[size]


def width(text, fs):
    return _font(100).getlength(text) * fs / 100 * SCALEX / 100 * CAL


def tokens_from_words(words):
    """palavras faladas -> tokens de tela, literais e em CAIXA ALTA (so tira virgula/ponto finais)."""
    out = []
    for w in words:
        t = w["w"].strip()
        t = re.sub(r"[.,;:]+$", "", t)
        if t.startswith("-") and out:            # "chemical -free" -> junta
            out[-1] += t
            continue
        out.append(t.upper())
    return out


def layout(tokens, max_w, fs_max, fs_min=60, max_lines=3, breaks=None, extra=None):
    """quebra em linhas equilibradas e escolhe o maior fs que cabe. breaks = [n palavras por linha] opcional.
    extra = {indice_token: largura_extra_em_fs} (ex.: icone)."""
    extra = extra or {}

    def lines_for(fs):
        if breaks:
            res, k = [], 0
            for n in breaks:
                res.append(list(range(k, k + n)))
                k += n
            return res
        best = None
        n = len(tokens)
        for nl in range(1, max_lines + 1):
            target = sum(width(t, fs) for t in tokens) / nl
            res, cur, cw = [], [], 0
            for i, t in enumerate(tokens):
                tw = width(t, fs) + extra.get(i, 0) * fs
                if cur and cw + tw > target * 1.18 and len(res) < nl - 1:
                    res.append(cur)
                    cur, cw = [], 0
                cur.append(i)
                cw += tw + width(" ", fs)
            res.append(cur)
            if all(line_w(l, fs) <= max_w for l in res):
                return res
            best = res
        return best

    def line_w(line, fs):
        return sum(width(tokens[i], fs) + extra.get(i, 0) * fs for i in line) + width(" ", fs) * (len(line) - 1)

    fs = fs_max
    while fs > fs_min:
        ls = lines_for(fs)
        if all(line_w(l, fs) <= max_w for l in ls):
            return ls, fs
        fs -= 4
    return lines_for(fs_min), fs_min


def ass_time(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def phrase_events(tokens, times, end, cx, cy, max_w, fs_max, colors, base="&H00FFFFFF",
                  big=None, breaks=None, icon=None, max_lines=3):
    """tokens + tempos (inicio de cada palavra) -> eventos ASS. colors = {indice: cor BGR}.
    big = {indice: fator de escala} (ex.: "$5" 1.9x). icon = {"after": indice, "w": largura_em_fs}.
    Retorna (eventos, posicao_do_icone|None)."""
    big = big or {}
    extra = {icon["after"]: icon["w"]} if icon else {}
    lines, fs = layout(tokens, max_w, fs_max, max_lines=max_lines, breaks=breaks, extra=extra)
    sp = width(" ", fs)
    lh = [fs * LINE_H * max(big.get(i, 1.0) for i in l) for l in lines]
    total_h = sum(lh)
    y = cy - total_h / 2
    ev, icon_pos = [], None
    for li, line in enumerate(lines):
        y_line = y + lh[li] / 2
        y += lh[li]
        ws = [width(tokens[i], fs * big.get(i, 1.0)) + extra.get(i, 0) * fs for i in line]
        x = cx - (sum(ws) + sp * (len(line) - 1)) / 2
        for i, w_ in zip(line, ws):
            f_i = fs * big.get(i, 1.0)
            tw = width(tokens[i], f_i)
            xc = x + tw / 2
            if icon and i == icon["after"]:
                icon_pos = (x + tw + 0.08 * fs, y_line, f_i)
            t0 = times[i] - 0.04
            col = colors.get(i, base)
            fx = f"\\fn{FONT_NAME}\\b1\\fs{int(f_i)}\\fscx{int(SCALEX * 0.86)}\\fscy86"
            mv = f"\\move({xc:.0f},{y_line + 28:.0f},{xc:.0f},{y_line:.0f},0,180)"
            anim = f"\\t(0,180,\\fscx{SCALEX}\\fscy100)"
            txt = tokens[i].replace("{", "").replace("}", "")
            # halo escuro por tras (fill invisivel) — efeito so por fora
            ev.append(f"Dialogue: 5,{ass_time(t0)},{ass_time(end)},C,,0,0,0,,{{\\an5{mv}{fx}{anim}\\1a&HFF&"
                      f"\\3c&H000000&\\3a&H68&\\bord11\\blur12\\shad0\\fad(110,160)}}{txt}")
            ev.append(f"Dialogue: 6,{ass_time(t0)},{ass_time(end)},C,,0,0,0,,{{\\an5{mv}{fx}{anim}\\1c{col}"
                      f"\\bord0\\shad3\\4c&H000000&\\4a&H70&\\fad(90,160)}}{txt}")
            x += w_ + sp
    return ev, icon_pos


def render_icon(emoji, size_px, out_mov, fps=30, hold=6.0):
    """emoji colorido -> .mov com alpha: pop 0->115%->100% em 8 frames, depois parado."""
    if os.path.exists(out_mov):
        return out_mov
    tmp = out_mov + "_frames"
    os.makedirs(tmp, exist_ok=True)
    f = ImageFont.truetype(EMOJI_FILE, 109)
    base = Image.new("RGBA", (160, 160), (0, 0, 0, 0))
    ImageDraw.Draw(base).text((80, 80), emoji, font=f, embedded_color=True, anchor="mm")
    base = base.crop(base.getbbox())
    S = size_px + 8
    curve = [0.0, 0.45, 0.85, 1.12, 1.15, 1.08, 1.02, 1.0]
    n = int(hold * fps)
    for k in range(n):
        s = curve[k] if k < len(curve) else 1.0
        fr = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        if s > 0:
            sz = max(1, int(size_px / 1.15 * s))
            im = base.resize((sz, int(sz * base.height / base.width)), Image.LANCZOS)
            fr.paste(im, ((S - im.width) // 2, (S - im.height) // 2), im)
        fr.save(os.path.join(tmp, f"{k:04d}.png"))
    import subprocess
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", os.path.join(tmp, "%04d.png"),
                    "-c:v", "qtrle", "-pix_fmt", "argb", out_mov], check=True)
    for fn in os.listdir(tmp):
        os.remove(os.path.join(tmp, fn))
    os.rmdir(tmp)
    return out_mov

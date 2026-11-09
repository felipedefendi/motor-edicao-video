r"""Varre o video com OCR procurando palavras proibidas escritas na tela (letreiros e legendas).

Uso: py -3.12 motor\varrer_letreiros.py <video.mp4> <saida.json> [fps=2] [termos=memo,flow,gota]
Le o video em 540 px de largura, roda easyocr (es/en) e grava cada achado com tempo e texto.
"""
import json
import re
import subprocess
import sys

import easyocr
import numpy as np

src, dst = sys.argv[1], sys.argv[2]
fps = float(sys.argv[3]) if len(sys.argv) > 3 else 2.0
termos = (sys.argv[4] if len(sys.argv) > 4 else "memo,flow,gota").split(",")
W, H = 540, 960
p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", src, "-vf", f"fps={fps},scale={W}:{H}",
                      "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
leitor = easyocr.Reader(["es", "en"], gpu=False, verbose=False)
achados, k = [], 0
while True:
    raw = p.stdout.read(W * H * 3)
    if len(raw) < W * H * 3:
        break
    img = np.frombuffer(raw, np.uint8).reshape(H, W, 3)
    txt = " ".join(t for _, t, c in leitor.readtext(img) if c > 0.3)
    if any(re.search(t, txt, re.I) for t in termos):
        achados.append({"t": round(k / fps, 2), "texto": txt})
        print(achados[-1], flush=True)
    k += 1
json.dump(achados, open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"{k} quadros, {len(achados)} achados -> {dst}")

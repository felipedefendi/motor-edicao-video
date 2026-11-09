r"""Devolve o texto de preco/oferta do ORIGINAL por cima do clipe novo, sem trazer nada do pote antigo.

Uso:
  py -3.12 motor\restaurar_texto.py jobs\<job> <id> --previa <t>     # 1 quadro lado a lado
  py -3.12 motor\restaurar_texto.py jobs\<job> <id>                  # gera o clipe com texto

Receita em jobs/<job>/docs/textos.json:
{
  "5": {"clipe": "work/clipes/J5_flow.mp4", "saida": "work/clipes/J5_final.mp4",
        "inicio": 33.167, "fim": 36.333, "cor": "verde", "contorno": 7}
}

Por que assim: o preco foi queimado no video original POR CIMA do pote antigo. Recortar o retangulo do
texto traria junto pedacos do rotulo antigo (dois produtos na tela). Aqui so entram os pixels cuja cor
e a do texto (verde neon ou vermelho puro, saturados e claros); o contorno preto e REDESENHADO a partir
da forma das letras, nao copiado. Numero, fonte, posicao e animacao continuam sendo os do original â€”
risco zero de digitar preco errado.
"""
import json
import os
import subprocess
import sys

import cv2
import numpy as np

FAIXAS = {
    # OpenCV HSV: H 0-180. Limites apertados de S e V separam o texto de folhagem e luz quente.
    "verde": [((38, 150, 150), (85, 255, 255))],
    "vermelho": [((0, 150, 120), (8, 255, 255)), ((172, 150, 120), (180, 255, 255))],
}


def ffprobe_fps(src):
    o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate", "-of", "json", src],
                       capture_output=True, text=True)
    v = json.loads(o.stdout)["streams"][0]
    n, _, d = v["r_frame_rate"].partition("/")
    return int(v["width"]), int(v["height"]), float(n) / float(d or 1)


def mascara(frame, cor, receita=None):
    receita = receita or {}
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = np.zeros(frame.shape[:2], np.uint8)
    for lo, hi in receita.get("faixas_hsv", FAIXAS[cor]):
        m |= cv2.inRange(hsv, np.array(lo), np.array(hi))
    if receita.get("roi"):
        x0,y0,x1,y1 = receita["roi"]
        limitado = np.zeros_like(m)
        limitado[y0:y1,x0:x1] = m[y0:y1,x0:x1]
        m = limitado
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    fechar = receita.get("fechar", 0)
    if fechar:
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((fechar, fechar), np.uint8))
    # descartar manchas pequenas: texto de preco e grande
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    for i in range(1, n):
        if st[i, cv2.CC_STAT_AREA] >= 120:
            keep[lab == i] = 255
    return keep


def aplicar(novo, orig, cor, contorno, receita=None):
    receita = receita or {}
    m = mascara(orig, cor, receita)
    if not m.any():
        return novo
    ys, xs = np.nonzero(m)
    margem = max(8, contorno * 6)
    x0, x1 = max(0, int(xs.min())-margem), min(novo.shape[1], int(xs.max())+margem+1)
    y0, y1 = max(0, int(ys.min())-margem), min(novo.shape[0], int(ys.max())+margem+1)
    base = novo
    novo, orig, m = novo[y0:y1,x0:x1], orig[y0:y1,x0:x1], m[y0:y1,x0:x1]
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * contorno + 1, 2 * contorno + 1))
    borda = cv2.dilate(m, k)
    sombra = cv2.GaussianBlur(cv2.dilate(m, k, iterations=2), (0, 0), contorno)
    out = novo.astype(np.float32)
    a_s = (sombra.astype(np.float32) / 255.0)[..., None] * 0.55
    out = out * (1 - a_s)                                   # sombra suave
    a_b = cv2.GaussianBlur(borda, (3, 3), 0).astype(np.float32)[..., None] / 255.0
    out = out * (1 - a_b)                                   # contorno preto redesenhado
    a_t = cv2.GaussianBlur(m, (3, 3), 0).astype(np.float32)[..., None] / 255.0
    tinta = np.array(receita["tinta_bgr"], dtype=np.float32) if "tinta_bgr" in receita else orig.astype(np.float32)
    out = out * (1 - a_t) + tinta * a_t   # so os pixels do texto vem do original
    resultado = base.copy()
    resultado[y0:y1,x0:x1] = np.clip(out, 0, 255).astype(np.uint8)
    return resultado


def main():
    job = sys.argv[1].rstrip("\\/")
    jid = sys.argv[2]
    tprev = float(sys.argv[sys.argv.index("--previa") + 1]) if "--previa" in sys.argv else None
    rec = json.load(open(os.path.join(job, "docs", "textos.json"), encoding="utf-8-sig"))[jid]
    src = os.path.join(job, "entrada", "original.mp4")
    W, H, FPS = ffprobe_fps(src)
    co = cv2.VideoCapture(src)
    co.set(cv2.CAP_PROP_POS_FRAMES, int(round(rec["inicio"] * FPS)))
    cn = cv2.VideoCapture(os.path.join(job, rec["clipe"]))
    n = int(round((rec["fim"] - rec["inicio"]) * FPS))
    alvo = int(round((tprev - rec["inicio"]) * FPS)) if tprev is not None else -1

    saida = None
    if tprev is None:
        dst = os.path.join(job, rec["saida"])
        saida = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}",
             "-r", f"{FPS}", "-i", "-", "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
             "-pix_fmt", "yuv420p", dst], stdin=subprocess.PIPE)
    k = 0
    for k in range(n + 3):
        ok1, fo = co.read()
        ok2, fn = cn.read()
        if not (ok1 and ok2):
            break
        if fn.shape[:2] != (H, W):
            fn = cv2.resize(fn, (W, H), interpolation=cv2.INTER_LANCZOS4)
        out = aplicar(fn, fo, rec["cor"], rec.get("contorno", 7), rec)
        if tprev is not None:
            if k == alvo:
                lado = np.hstack([cv2.resize(fo, (W // 3, H // 3)), cv2.resize(out, (W // 3, H // 3))])
                p = os.path.join(job, "work", f"previa_texto_J{jid}_{tprev:.2f}.png")
                cv2.imwrite(p, lado)
                print(f"previa (original | novo com texto): {p}")
                break
        else:
            saida.stdin.write(out.tobytes())
    co.release()
    cn.release()
    if saida:
        saida.stdin.close()
        saida.wait()
        print(f"{k} quadros -> {os.path.join(job, rec['saida'])}")


if __name__ == "__main__":
    main()

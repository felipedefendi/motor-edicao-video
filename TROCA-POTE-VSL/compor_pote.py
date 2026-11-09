r"""Compoe o pote novo sobre uma janela do video original, rastreando a camera quadro a quadro.

Uso:
  py -3.12 motor\compor_pote.py jobs\<job> <id_da_janela> --previa <t>   # 1 quadro, para olhar
  py -3.12 motor\compor_pote.py jobs\<job> <id_da_janela>                # a janela inteira

Le a receita em jobs/<job>/docs/composicao.json:
{
  "4": {
    "pote": "biblioteca/potes/<slug>/recortes/x.png",   # caminho relativo a raiz da skill
    "inicio": 1.833, "fim": 8.400,
    "base_x": 495, "base_y": 1530,        # centro e linha de apoio do pote novo, no 1o quadro
    "altura": 980,                        # altura do pote novo em px
    "reparo": [280, 400, 430, 580],       # x0,y0,x1,y1 da faixa a reconstruir (gargalo antigo)
    "sombra": {"op": 0.45, "rx": 0.52, "ry": 26},
    "reflexo": {"forca": 0.0},
    "cor": [1.0, 1.0, 1.0],               # ganho B,G,R para casar a luz da cena
    "brilho": 1.0
  }
}

O que o script garante:
- **rastreio**: o deslocamento global da cena e medido por correlacao de fase contra o 1o quadro da
  janela, e o pote acompanha. Sem isso o pote "desliza" em relacao a mesa.
- **reparo por espelho**: a faixa do gargalo antigo e preenchida espelhando a banda limpa de cima.
- saida com a duracao exata da janela, no fps do original, SEM audio.
"""
import json
import os
import subprocess
import sys

import cv2
import numpy as np

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ffprobe(src):
    o = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate", "-of", "json", src],
                       capture_output=True, text=True)
    v = json.loads(o.stdout)["streams"][0]
    n, _, d = v["r_frame_rate"].partition("/")
    return int(v["width"]), int(v["height"]), float(n) / float(d or 1)


def reparar(base, cx0, y0, cx1, y1, modo="suave", pena=25, escala=8):
    """Reconstroi o retangulo onde estava o gargalo antigo.

    modo 'suave' (padrao, para fundo desfocado): reduz o quadro, reconstroi na miniatura e amplia de
    volta. Na escala reduzida o preenchimento vira um degrade sem forma, que e exatamente o que um
    fundo fora de foco parece. Evita a emenda retangular do espelho.
    modo 'espelho': copia espelhada a banda de cima. So serve quando o fundo tem estrutura vertical
    continua (feixes de luz, cortina), nunca quando tem bokeh lateral diferente.
    """
    H, W = base.shape[:2]
    cx0, y0 = max(0, cx0), max(0, y0)
    cx1, y1 = min(W, cx1), min(H, y1)
    if cx1 <= cx0 or y1 <= y0:
        return base.copy()
    m = np.zeros((H, W), np.uint8)
    cv2.rectangle(m, (cx0, y0), (cx1, y1), 255, -1)

    if modo == "espelho":
        out = base.copy()
        alt = y1 - y0
        banda = cv2.flip(base[max(0, y0 - alt):y0, cx0:cx1], 0)
        if banda.shape[0] < alt:
            banda = cv2.resize(banda, (cx1 - cx0, alt), interpolation=cv2.INTER_LINEAR)
        out[y0:y1, cx0:cx1] = banda[:alt]
    else:
        pq = cv2.resize(base, (W // escala, H // escala), interpolation=cv2.INTER_AREA)
        mq = cv2.resize(m, (W // escala, H // escala), interpolation=cv2.INTER_NEAREST)
        mq = cv2.dilate(mq, np.ones((3, 3), np.uint8), 1)
        fill = cv2.inpaint(pq, mq, 6, cv2.INPAINT_TELEA)
        out = cv2.resize(fill, (W, H), interpolation=cv2.INTER_LINEAR)
        out = cv2.GaussianBlur(out, (0, 0), 3)

    a = cv2.GaussianBlur(m, (0, 0), pena).astype(np.float32)[..., None] / 255.0
    return (out.astype(np.float32) * a + base.astype(np.float32) * (1 - a)).astype(np.uint8)


def seguir(orb, bf, kp0, des0, g, escala=4):
    """Similaridade (escala + translacao) do 1o quadro ate este, em pixels do quadro cheio.

    Correlacao de fase so mede translacao: num plano em que a camera AFASTA, ela erra e o objeto
    novo sai de escala, deixando o antigo reaparecer. ORB + estimateAffinePartial2D pega a escala.
    """
    kp1, des1 = orb.detectAndCompute(g, None)
    if des0 is None or des1 is None or len(kp1) < 8:
        return 1.0, 0.0, 0.0
    pares = bf.knnMatch(des0, des1, k=2)
    bons = [m for m, n in (p for p in pares if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(bons) < 8:
        return 1.0, 0.0, 0.0
    a = np.float32([kp0[m.queryIdx].pt for m in bons])
    b = np.float32([kp1[m.trainIdx].pt for m in bons])
    M, _ = cv2.estimateAffinePartial2D(a, b, method=cv2.RANSAC, ransacReprojThreshold=3)
    if M is None:
        return 1.0, 0.0, 0.0
    s = float(np.hypot(M[0, 0], M[0, 1]))
    if not (0.5 < s < 2.0):
        return 1.0, 0.0, 0.0
    return s, float(M[0, 2]) * escala, float(M[1, 2]) * escala


def sombra(base, cx, by, larg, op, rx, ry, desfoque=35):
    """Sombra de contato suave. Elipse dura denuncia a montagem na hora."""
    m = np.zeros(base.shape[:2], np.float32)
    cv2.ellipse(m, (int(cx), int(by) - 6), (int(larg * rx), int(ry)), 0, 0, 360, 1.0, -1)
    m = cv2.GaussianBlur(m, (0, 0), desfoque)[..., None] * op
    base[:] = (base.astype(np.float32) * (1 - m)).astype(np.uint8)


def por(base, pote, cx, by, altura, cor, brilho):
    ph, pw = pote.shape[:2]
    f = altura / ph
    p = cv2.resize(pote, (max(1, int(pw * f)), int(altura)), interpolation=cv2.INTER_AREA)
    h2, w2 = p.shape[:2]
    rgb = p[:, :, :3].astype(np.float32) * np.array(cor, np.float32) * brilho
    rgb = np.clip(rgb, 0, 255)
    x, y = int(cx - w2 / 2), int(by - h2)
    H, W = base.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w2), min(H, y + h2)
    if x1 <= x0 or y1 <= y0:
        return
    a = (p[y0 - y:y1 - y, x0 - x:x1 - x, 3:4].astype(np.float32) / 255.0)
    roi = base[y0:y1, x0:x1].astype(np.float32)
    base[y0:y1, x0:x1] = (rgb[y0 - y:y1 - y, x0 - x:x1 - x] * a + roi * (1 - a)).astype(np.uint8)


def main():
    job = sys.argv[1].rstrip("\\/")
    jid = sys.argv[2]
    tprev = float(sys.argv[sys.argv.index("--previa") + 1]) if "--previa" in sys.argv else None

    rec = json.load(open(os.path.join(job, "docs", "composicao.json"), encoding="utf-8-sig"))[jid]
    src = os.path.join(job, "entrada", "original.mp4")
    W, H, FPS = ffprobe(src)
    pote = cv2.imread(os.path.join(RAIZ, rec["pote"]), cv2.IMREAD_UNCHANGED)
    if pote is None or pote.shape[2] != 4:
        raise SystemExit("o recorte do pote precisa ter canal alfa")

    rx0, ry0, rx1, ry1 = rec["reparo"]
    sb = rec.get("sombra", {"op": 0.45, "rx": 0.52, "ry": 26})
    cor = rec.get("cor", [1.0, 1.0, 1.0])
    brilho = rec.get("brilho", 1.0)
    larg = pote.shape[1] * rec["altura"] / pote.shape[0]

    cap = cv2.VideoCapture(src)
    i0 = int(round(rec["inicio"] * FPS))
    n = int(round((rec["fim"] - rec["inicio"]) * FPS))
    cap.set(cv2.CAP_PROP_POS_FRAMES, i0)

    saida, ref, kp0, des0 = None, None, None, None
    orb = cv2.ORB_create(1500)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    if tprev is None:
        os.makedirs(os.path.join(job, "work", "clipes"), exist_ok=True)
        dst = os.path.join(job, "work", "clipes", f"J{jid}_2d.mp4")
        saida = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
             "-s", f"{W}x{H}", "-r", f"{FPS}", "-i", "-", "-an",
             "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-pix_fmt", "yuv420p", dst],
            stdin=subprocess.PIPE)

    alvo = int(round((tprev - rec["inicio"]) * FPS)) if tprev is not None else -1
    for k in range(n):
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(f, (W // 4, H // 4)), cv2.COLOR_BGR2GRAY)
        if ref is None:
            ref = g
            kp0, des0 = orb.detectAndCompute(ref, None)
            s, dx, dy = 1.0, 0.0, 0.0
        else:
            s, dx, dy = seguir(orb, bf, kp0, des0, g)
        # escala E posicao: so translacao nao basta, ha planos em que a camera afasta (dolly)
        cx = rec["base_x"] * s + dx
        by = rec["base_y"] * s + dy
        alt = rec["altura"] * s
        lg = larg * s
        out = reparar(f, int(rx0 * s + dx), int(ry0 * s + dy), int(rx1 * s + dx), int(ry1 * s + dy),
                      rec.get("reparo_modo", "suave"), rec.get("pena", 25))
        sombra(out, cx, by, lg, sb["op"], sb["rx"], sb["ry"], sb.get("desfoque", 35))
        por(out, pote, cx, by, alt, cor, brilho)
        if tprev is not None:
            if k == alvo:
                p = os.path.join(job, "work", f"previa_J{jid}_{tprev:.2f}.png")
                cv2.imwrite(p, out)
                print(f"previa: {p}  (deslocamento dx={dx:.1f} dy={dy:.1f})")
                break
        else:
            saida.stdin.write(out.tobytes())
    cap.release()
    if saida:
        saida.stdin.close()
        saida.wait()
        print(f"{n} quadros -> {os.path.join(job, 'work', 'clipes', f'J{jid}_2d.mp4')}")


if __name__ == "__main__":
    main()

r"""Recorta o pote de uma foto de fundo liso e salva PNG com alfa (+ previa em xadrez).

Uso:  py -3.12 motor\recortar_pote.py <foto.png> <saida.png> [--margem 6]

Como decide o que e fundo: pega a cor mediana da moldura externa da imagem, marca como fundo tudo que
estiver perto dessa cor, fica com o maior componente conectado restante, fecha buracos (rotulo escuro
e reflexo nao podem virar furo) e suaviza a borda para o recorte nao serrilhar quando for composto.

Sempre OLHAR a previa antes de usar: fundo com sombra forte ou pote da cor do fundo quebram o metodo.
"""
import os
import sys

import cv2
import numpy as np


def recortar(src, dst, margem=6, tol=None):
    img = cv2.imread(src, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"nao consegui abrir {src}")
    h, w = img.shape[:2]
    m = margem
    moldura = np.concatenate([img[:m].reshape(-1, 3), img[-m:].reshape(-1, 3),
                              img[:, :m].reshape(-1, 3), img[:, -m:].reshape(-1, 3)])
    bg = np.median(moldura, axis=0)
    ruido = float(np.median(np.abs(moldura - bg))) or 1.0
    tol = tol if tol is not None else max(18.0, ruido * 6)

    dist = np.linalg.norm(img.astype(np.float32) - bg, axis=2)
    mask = (dist > tol).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8), iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8), iterations=3)

    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    if n < 2:
        raise SystemExit("nao achei objeto: fundo e objeto tem cores parecidas demais")
    maior = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = (lab == maior).astype(np.uint8) * 255

    # fechar buracos internos (rotulo escuro, reflexo) sem comer a silhueta
    cont, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cheia = np.zeros_like(mask)
    cv2.drawContours(cheia, cont, -1, 255, cv2.FILLED)
    mask = cheia

    alpha = cv2.GaussianBlur(mask, (5, 5), 0)
    x, y, bw, bh = cv2.boundingRect(mask)
    out = np.dstack([img, alpha])[y:y + bh, x:x + bw]
    cv2.imwrite(dst, out)

    # previa em xadrez, para eu enxergar falha de borda e buraco
    xad = np.zeros((bh, bw, 3), np.uint8)
    q = 16
    for i in range(0, bh, q):
        for j in range(0, bw, q):
            xad[i:i + q, j:j + q] = 200 if ((i // q + j // q) % 2 == 0) else 120
    a = out[:, :, 3:4].astype(np.float32) / 255.0
    prev = (out[:, :, :3].astype(np.float32) * a + xad.astype(np.float32) * (1 - a)).astype(np.uint8)
    pv = os.path.splitext(dst)[0] + "_previa.png"
    cv2.imwrite(pv, prev)
    print(f"fundo {bg.astype(int).tolist()} | tolerancia {tol:.1f} | recorte {bw}x{bh}")
    print(f"  {dst}\n  {pv}  <- olhar esta antes de usar")


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    mg = int(sys.argv[sys.argv.index("--margem") + 1]) if "--margem" in sys.argv else 6
    recortar(a[0], a[1], mg)

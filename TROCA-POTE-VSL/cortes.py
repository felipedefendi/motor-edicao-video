r"""Lista os cortes de cena e monta uma folha com UM quadro por plano.

Uso:  py -3.12 motor\cortes.py jobs\<job> [limiar]        (limiar padrao 0.30)

Por que isso existe: a janela que vai ser trocada tem que comecar e terminar num CORTE, nao num
segundo redondo. Emenda no meio de um plano aparece; emenda no corte nao.

Gera em jobs/<job>/work/cortes/:
  planos.json        [{"n":1,"inicio":0.0,"fim":2.46,"dur":2.46}, ...]
  planos_000.png     folha 6x4 com o quadro do meio de cada plano, em ordem
Depois eu olho a folha, digo o que tem em cada plano e so os planos com pote/preco viram janela.
"""
import json
import os
import re
import subprocess
import sys

COLS, ROWS = 6, 4


def run(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(p.stderr[-2000:])
    return p.stdout


def main():
    job = sys.argv[1].rstrip("\\/")
    lim = float(sys.argv[2]) if len(sys.argv) > 2 else 0.30
    src = os.path.join(job, "entrada", "original.mp4")
    if not os.path.exists(src):
        cand = [f for f in os.listdir(os.path.join(job, "entrada")) if f.lower().endswith(".mp4")]
        src = os.path.join(job, "entrada", cand[0])
    out = os.path.join(job, "work", "cortes")
    os.makedirs(out, exist_ok=True)

    dur = float(json.loads(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "json", src]))["format"]["duration"])
    # o filtro lavfi movie= nao engole caminho do Windows com espaco e ':' -> ler do showinfo
    p = subprocess.run(["ffmpeg", "-v", "info", "-i", src, "-vf",
                        f"select='gt(scene,{lim})',showinfo", "-an", "-f", "null", "-"],
                       capture_output=True, text=True)
    ts = sorted({round(float(m.group(1)), 3)
                 for m in re.finditer(r"pts_time:([0-9.]+)", p.stderr)})

    bordas = [0.0] + [t for t in ts if 0.05 < t < dur - 0.05] + [dur]
    # numerar DEPOIS de filtrar: buraco na numeracao quebra a montagem da folha (image2 para no vao)
    planos = [{"inicio": round(a, 3), "fim": round(b, 3), "dur": round(b - a, 3)}
              for a, b in zip(bordas[:-1], bordas[1:]) if b - a > 0.08]
    for i, p in enumerate(planos, start=1):
        p["n"] = i
    with open(os.path.join(out, "planos.json"), "w", encoding="utf-8") as fh:
        json.dump(planos, fh, indent=2, ensure_ascii=False)

    # um quadro do meio de cada plano
    tmp = os.path.join(out, "_q")
    os.makedirs(tmp, exist_ok=True)
    for f in os.listdir(tmp):          # limpar: sobra da rodada anterior entra na folha e desalinha
        os.remove(os.path.join(tmp, f))
    for f in os.listdir(out):
        if f.startswith("planos_") and f.endswith(".png"):
            os.remove(os.path.join(out, f))
    for p in planos:
        t = (p["inicio"] + p["fim"]) / 2
        run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1",
             "-vf", "scale=240:-2", os.path.join(tmp, f"q{p['n']:04d}.png")])
    run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", os.path.join(tmp, "q%04d.png"),
         "-vf", f"tile={COLS}x{ROWS}:padding=4:color=0x202020", "-start_number", "0",
         os.path.join(out, "planos_%03d.png")])

    print(f"{len(planos)} planos | duracao {dur:.2f}s | limiar {lim}")
    for p in planos:
        print(f"  {p['n']:3d}  {p['inicio']:7.3f} -> {p['fim']:7.3f}  ({p['dur']:.2f}s)")


if __name__ == "__main__":
    main()

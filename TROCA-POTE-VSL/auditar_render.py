r"""Auditoria OBRIGATORIA do render antes da entrega (Passo 10 da SKILL.md).

Uso:  py -3.12 motor\auditar_render.py jobs\<job> [--exigir-igualdade]

Confere, quadro a quadro, que:
  1. o contrato tecnico bate (resolucao, fps, nb_frames, duracao);
  2. o audio e identico ao do original (MD5 do stream);
  3. fora das janelas trocadas, o quadro do render e igual ao do original;
  4. nenhum quadro do render carrega vestigio do pote antigo (assinatura de cor do rotulo);
e escreve docs/LAUDO_<data>.md, extraindo os quadros suspeitos para eu olhar um por um.

Entradas esperadas no job:
  entrada/<original>.mp4
  entrega/<render>.mp4                 (o mais recente)
  docs/janelas.json   -> [{"inicio": 12.4, "fim": 15.0, "metodo": "...", "trecho": 3}, ...]
  docs/pote_antigo/*.png              recortes do rotulo antigo (referencia da assinatura de cor)

O script nao aprova nada sozinho: ele reduz o video a uma lista curta de quadros para eu conferir.
"""
import datetime
import glob
import hashlib
import json
import os
import subprocess
import sys

import cv2
import numpy as np

BINS = (12, 8, 8)          # H, S, V
LIMIAR_SUSPEITO = 0.72     # correlacao de histograma acima disto = olhar o quadro
LIMIAR_DIFF = 0.0 if "--exigir-igualdade" in sys.argv else 1.0          # diff medio absoluto acima disto = quadro alterado


def run(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(f"falhou: {' '.join(args[:4])}...\n{p.stderr[-2000:]}")
    return p.stdout


def ffprobe_video(src):
    return json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                           "stream=width,height,r_frame_rate,nb_frames", "-show_entries",
                           "format=duration", "-of", "json", src]))


def md5_audio(src):
    out = run(["ffmpeg", "-v", "error", "-i", src, "-vn", "-c:a", "copy", "-f", "md5", "-"])
    return out.strip().replace("MD5=", "")


def hist(img):
    h = cv2.calcHist([cv2.cvtColor(img, cv2.COLOR_BGR2HSV)], [0, 1, 2], None, BINS,
                     [0, 180, 0, 256, 0, 256])
    return cv2.normalize(h, h).flatten()


def refs(job):
    d = os.path.join(job, "docs", "pote_antigo")
    out = []
    for p in sorted(glob.glob(os.path.join(d, "*.png")) + glob.glob(os.path.join(d, "*.jpg"))):
        img = cv2.imread(p)
        if img is not None:
            out.append((os.path.basename(p), hist(img)))
    return out


def main():
    job = sys.argv[1].rstrip("\\/")
    ent = glob.glob(os.path.join(job, "entrada", "*.mp4"))
    ren = sorted(glob.glob(os.path.join(job, "entrega", "*.mp4")), key=os.path.getmtime)
    if not ent or not ren:
        raise SystemExit("preciso de entrada/*.mp4 e entrega/*.mp4")
    orig, rend = ent[0], ren[-1]
    docs = os.path.join(job, "docs")
    susp_dir = os.path.join(job, "work", "suspeitos")
    os.makedirs(susp_dir, exist_ok=True)

    jp = os.path.join(docs, "janelas.json")
    janelas = json.load(open(jp, encoding="utf-8-sig")) if os.path.exists(jp) else []
    if not janelas:
        print("AVISO: docs/janelas.json ausente ou vazio -> o item 3 do laudo nao pode ser apurado.")

    po, pr = ffprobe_video(orig), ffprobe_video(rend)
    vo, vr = po["streams"][0], pr["streams"][0]
    linhas, falhas = [], []

    def checa(nome, a, b):
        ok = str(a) == str(b)
        linhas.append(f"| {nome} | `{a}` | `{b}` | {'OK' if ok else 'FALHA'} |")
        if not ok:
            falhas.append(nome)

    checa("largura", vo["width"], vr["width"])
    checa("altura", vo["height"], vr["height"])
    checa("fps", vo["r_frame_rate"], vr["r_frame_rate"])
    checa("nb_frames", vo.get("nb_frames"), vr.get("nb_frames"))
    checa("duracao", round(float(po["format"]["duration"]), 3),
          round(float(pr["format"]["duration"]), 3))
    checa("md5 do audio", md5_audio(orig), md5_audio(rend))

    n, _, d = vr["r_frame_rate"].partition("/")
    fps = float(n) / float(d or 1)
    dentro = [(j["inicio"], j["fim"]) for j in janelas]
    R = refs(job)
    if not R:
        print("AVISO: sem recortes em docs/pote_antigo/ -> o item 4 cai para inspecao manual das folhas.")

    co, cr = cv2.VideoCapture(orig), cv2.VideoCapture(rend)
    i, alterados_fora, suspeitos = 0, [], []
    quantidade_fora, maior_diff_fora = 0, 0.0
    while True:
        oko, fo = co.read()
        okr, fr = cr.read()
        if not (oko and okr):
            break
        t = i / fps
        na_janela = any(round(a * fps) <= i < round(b * fps) for a, b in dentro)
        if not na_janela and fo.shape == fr.shape:
            dif = float(np.mean(cv2.absdiff(fo, fr)))
            quantidade_fora += 1
            maior_diff_fora = max(maior_diff_fora, dif)
            if dif > LIMIAR_DIFF:
                alterados_fora.append(round(t, 3))
        if R:
            hr = hist(fr)
            for nome, href in R:
                c = float(cv2.compareHist(hr, href, cv2.HISTCMP_CORREL))
                if c >= LIMIAR_SUSPEITO:
                    suspeitos.append({"t": round(t, 3), "quadro": i, "ref": nome,
                                      "correl": round(c, 3)})
                    cv2.imwrite(os.path.join(susp_dir, f"q{i:06d}_t{t:08.3f}.png"), fr)
                    break
        i += 1
    co.release()
    cr.release()

    hoje = datetime.date.today().isoformat()
    L = [f"# Laudo de auditoria — {hoje}", "",
         f"- original: `{os.path.abspath(orig)}`", f"- render: `{os.path.abspath(rend)}`",
         f"- quadros comparados: {i}", f"- janelas trocadas declaradas: {len(janelas)}", "",
         "## 1-2. Contrato tecnico e audio", "",
         "| item | original | render | |", "|---|---|---|---|", *linhas, "",
         "## 3. Quadros fora das janelas trocadas", ""]
    if not dentro:
        L.append("NAO APURADO — `docs/janelas.json` ausente.")
    elif alterados_fora:
        L.append(f"**FALHA: {len(alterados_fora)} quadros alterados fora das janelas.** "
                 f"Primeiros segundos: {alterados_fora[:20]}")
        falhas.append("quadros fora das janelas")
    elif LIMIAR_DIFF == 0:
        L.append(f"OK — {quantidade_fora} quadros fora das janelas com pixels decodificados identicos ao original; "
                 f"maior diferenca media = {maior_diff_fora}. Verificacao estrita, sem tolerancia a reencode.")
    else:
        L.append(f"OK — nenhum quadro fora das janelas tem alteracao perceptivel "
                 f"(diff medio < {LIMIAR_DIFF} de 255). Nao e igualdade byte a byte: o reencode do "
                 f"H.264 introduz ruido da ordem de 0.2, e o limiar existe para tolerar isso.")
    L += ["", "## 4. Vestigio do produto antigo", ""]
    if not R:
        L.append("NAO APURADO automaticamente — sem recortes de referencia em `docs/pote_antigo/`. "
                 "Conferir pelas folhas de contato do render.")
    elif suspeitos:
        L.append(f"**{len(suspeitos)} quadros suspeitos** extraidos em `work/suspeitos/` — "
                 "conferir um por um antes de qualquer entrega:")
        L += ["", "| quadro | t (s) | referencia | correl |", "|---|---|---|---|"]
        L += [f"| {s['quadro']} | {s['t']} | {s['ref']} | {s['correl']} |" for s in suspeitos[:200]]
        if len(suspeitos) > 200:
            L.append(f"| ... | +{len(suspeitos) - 200} | | |")
    else:
        L.append("Nenhum quadro acima do limiar de semelhanca com o rotulo antigo.")
    L += ["", "## 5. O que esta auditoria NAO apura", "",
          "Movimento percebido, ritmo e beleza da emenda. Isso continua sendo julgamento do Felipe, "
          "assistindo. A auditoria tambem nao reconhece o pote antigo quando ele aparece com cor "
          "muito diferente da dos recortes de referencia — por isso os recortes tem que cobrir os "
          "angulos e as luzes em que ele aparecia na VSL.", "",
          f"## Veredito: {'REPROVADO — ' + ', '.join(sorted(set(falhas))) if falhas else 'passou nas verificacoes automaticas'}"]
    if not falhas and suspeitos:
        L[-1] += " (com quadros suspeitos para conferir a mao)"

    p = os.path.join(docs, f"LAUDO_{hoje}.md")
    open(p, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"laudo: {p}")
    print(L[-1])


if __name__ == "__main__":
    main()

r"""Troca palavras/trechos da fala do narrador mantendo trilha, duracao e o resto do audio intactos.

Uso: py -3.12 motor\trocar_fala.py jobs\<job> <tts.mp3> <tts.json whisper> [--so G1,M3] [--previa]

Receita em jobs/<job>/docs/trocas_fala.json:
  {"roteiro": "docs/tts_roteiro.txt",
   "trocas": [{"id": "M1", "linha": 1, "alvo": "CogniHoney", "inicio": 2.24, "fim": 2.76}, ...]}
- linha: numero da frase no roteiro (1-based, separadas por linha em branco);
- alvo: as palavras do roteiro que entram no lugar de [inicio, fim] do original.

Como funciona, por troca:
1. alinha o roteiro com a transcricao Whisper da geracao (difflib) e pega o trecho do alvo entre as
   palavras-ancora vizinhas; apara silencio;
2. Demucs (htdemucs, 2 stems) numa janela de +-3 s do original -> voz / trilha;
3. iguala RMS da voz nova ao da voz original no trecho; ajusta duracao (atempo 0.75-1.33, depois
   pad/corte) para caber exatamente em [inicio, fim];
4. regiao = trilha original separada + voz nova; fora dela, audio original; crossfade de 15 ms.
Saida: work/voz/audio_novo.wav (PCM 48k) e work/voz/trocas/<id>.wav (para conferencia).
"""
import difflib
import json
import os
import re
import subprocess
import sys
import unicodedata

import numpy as np
import soundfile as sf

SR = 44100


def norm(w):
    w = unicodedata.normalize("NFKD", w.lower())
    w = "".join(c for c in w if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", w)


def ff_audio(src, a=None, d=None, sr=SR):
    cmd = ["ffmpeg", "-v", "error"]
    if a is not None:
        cmd += ["-ss", f"{a:.4f}"]
    cmd += ["-i", src]
    if d is not None:
        cmd += ["-t", f"{d:.4f}"]
    cmd += ["-vn", "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).reshape(-1, 2).copy()


def demucs_split(x):
    import torch
    from demucs.apply import apply_model
    from demucs.pretrained import get_model
    global _MODEL
    if "_MODEL" not in globals():
        _MODEL = get_model("htdemucs")
        _MODEL.eval()
    wav = torch.from_numpy(x.T.copy()).float()
    ref = wav.mean(0)
    wav_n = (wav - ref.mean()) / (ref.std() + 1e-8)
    with torch.no_grad():
        out = apply_model(_MODEL, wav_n[None], device="cpu", progress=False)[0]
    out = out * (ref.std() + 1e-8) + ref.mean()
    srcs = _MODEL.sources
    voc = out[srcs.index("vocals")].numpy().T
    acc = x - voc  # trilha = original - voz: soma de volta exatamente ao original
    return voc, acc


def rms(x):
    return float(np.sqrt(np.mean(x ** 2) + 1e-12))


def aparar(x, thr_db=-38):
    e = np.abs(x).max(1)
    thr = 10 ** (thr_db / 20) * max(e.max(), 1e-6)
    idx = np.where(e > thr)[0]
    if len(idx) == 0:
        return x
    return x[max(0, idx[0] - int(0.005 * SR)): idx[-1] + int(0.02 * SR)]


def caber(x, n, preservar_ritmo=False):
    """Ajusta a duracao de x para n amostras: atempo limitado, depois pad/corte suave."""
    fator = len(x) / n
    if preservar_ritmo:
        if len(x) > n:
            raise ValueError("Fonte revisada excede janela; revisar limites ou regerar, nao cortar fonemas")
        pad = n - len(x)
        return np.pad(x, ((pad // 2, pad - pad // 2), (0, 0))), fator
    f = min(1.4, max(0.75, fator))
    if abs(f - 1) > 0.01:
        p = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ac", "2", "-ar", str(SR), "-i", "-",
                            "-af", f"atempo={f:.4f}", "-f", "f32le", "-"],
                           input=x.astype(np.float32).tobytes(), capture_output=True, check=True)
        x = np.frombuffer(p.stdout, np.float32).reshape(-1, 2).copy()
    if len(x) >= n:
        x = x[:n]
        fade = min(int(0.012 * SR), n)
        x[-fade:] *= np.linspace(1, 0, fade)[:, None]
    else:
        pad = n - len(x)
        x = np.vstack([np.zeros((pad // 2, 2), np.float32), x, np.zeros((pad - pad // 2, 2), np.float32)])
    return x, fator


def localizar(roteiro_linhas, palavras_tts, linha, alvo):
    """Devolve (t0, t1) do alvo na geracao, usando as palavras vizinhas como ancora."""
    esperado, marca = [], []
    for i, l in enumerate(roteiro_linhas, 1):
        for w in l.split():
            esperado.append(norm(w))
            marca.append(i)
    alvo_n = [norm(w) for w in alvo.split()]
    # posicao do alvo na linha esperada
    pos = None
    for k in range(len(esperado)):
        if marca[k] == linha and esperado[k:k + len(alvo_n)] == alvo_n:
            pos = k
            break
    if pos is None:
        raise ValueError(f"alvo '{alvo}' nao achado na linha {linha}")
    obtido = [norm(w["word"]) for w in palavras_tts]
    sm = difflib.SequenceMatcher(None, esperado, obtido, autojunk=False)
    mapa = {}
    for blk in sm.get_matching_blocks():
        for j in range(blk.size):
            mapa[blk.a + j] = blk.b + j
    antes = max((k for k in mapa if k < pos), default=None)
    depois = min((k for k in mapa if k >= pos + len(alvo_n)), default=None)
    t0 = palavras_tts[mapa[antes]]["end"] if antes is not None else 0.0
    t1 = palavras_tts[mapa[depois]]["start"] if depois is not None else palavras_tts[-1]["end"] + 0.3
    # se o proprio alvo foi reconhecido, usa os tempos dele (mais justo)
    dentro = [mapa[k] for k in range(pos, pos + len(alvo_n)) if k in mapa]
    if len(dentro) == len(alvo_n):
        t0 = palavras_tts[dentro[0]]["start"]
        t1 = palavras_tts[dentro[-1]]["end"]
    return t0, t1


def main():
    job = sys.argv[1].rstrip("\\/")
    tts, tjson = sys.argv[2], sys.argv[3]
    so = set(sys.argv[sys.argv.index("--so") + 1].split(",")) if "--so" in sys.argv else None
    rec = json.load(open(os.path.join(job, "docs", "trocas_fala.json"), encoding="utf-8-sig"))
    if rec.get("reparos_contextuais"):
        raise SystemExit("Receita possui reparos contextuais posteriores. Use o audio vigente registrado e aplique patches incrementais; regenerar esta receita isolada perderia as correcoes. Consulte CONTINUAR.md e reparos_contextuais.")
    linhas = [l.strip() for l in open(os.path.join(job, rec["roteiro"]), encoding="utf-8").read().split("\n\n")
              if l.strip()]
    w = json.load(open(tjson, encoding="utf-8"))
    palavras = [p for s in w["segments"] for p in s["words"]]
    src = os.path.join(job, "entrada", "original.mp4")
    voz_tts = ff_audio(tts)
    out_dir = os.path.join(job, "work", "voz", "trocas")
    os.makedirs(out_dir, exist_ok=True)

    full = ff_audio(src)
    novo = full.copy()
    log = []
    for t in rec["trocas"]:
        if so and t["id"] not in so:
            continue
        a, b = t["inicio"], t["fim"]
        auto0, auto1 = localizar(linhas, palavras, t["linha"], t["alvo"])
        manual = "fonte_inicio" in t or "fonte_fim" in t
        if manual and not ("fonte_inicio" in t and "fonte_fim" in t):
            raise ValueError(f"{t['id']}: informe os dois limites foneticos da fonte")
        t0, t1 = (float(t["fonte_inicio"]), float(t["fonte_fim"])) if manual else (auto0, auto1)
        if not (0 <= t0 < t1 <= len(voz_tts) / SR):
            raise ValueError(f"{t['id']}: limites invalidos da fonte")
        # Limites manuais revisados preservam as margens foneticas; nao aparar de novo.
        trecho_fonte = voz_tts[int(round(t0 * SR)): int(round(t1 * SR))]
        seg = trecho_fonte.copy() if manual else aparar(trecho_fonte)
        if not manual:
            print(f"AVISO {t['id']}: limites automaticos; revisar fonte e emenda final em contexto", flush=True)
        jan_a = max(0.0, a - 3.0)
        ia, ib = int(a * SR), int(b * SR)
        ja, jb = int(jan_a * SR), int((b + 3.0) * SR)
        voc, acc = demucs_split(full[ja:jb])
        voc_orig = voc[ia - ja: ib - ja]
        seg = seg * (rms(voc_orig) / max(rms(seg), 1e-6))
        seg, fator = caber(seg, ib - ia, preservar_ritmo=t.get("preservar_ritmo", False))
        comp = acc[ia - ja: ib - ja] + seg
        xf = int(0.015 * SR)
        r = np.linspace(0, 1, xf)[:, None]
        orig = full[ia:ib]
        comp[:xf] = orig[:xf] * (1 - r) + comp[:xf] * r
        comp[-xf:] = comp[-xf:] * (1 - r) + orig[-xf:] * r
        novo[ia:ib] = comp
        sf.write(os.path.join(out_dir, f"{t['id']}.wav"),
                 novo[max(0, ia - SR):ib + SR], SR)
        log.append(f"{t['id']}: {a:.2f}-{b:.2f}s <- tts {t0:.2f}-{t1:.2f}s  fator {fator:.2f}")
        print(log[-1], flush=True)
    if "--previa" not in sys.argv:
        dst = os.path.join(job, "work", "voz", "audio_novo.wav")
        sf.write(dst, np.clip(novo, -1, 1), SR, subtype="FLOAT")
        print("audio ->", dst)
    with open(os.path.join(out_dir, "log.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(log))


if __name__ == "__main__":
    main()

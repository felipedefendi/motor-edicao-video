"""Banco de SFX reais (Mixkit, licenca livre sem atribuicao) para a montagem v4.

Para cada sample: baixa (wav; fallback preview mp3), corta silencio inicial (transiente no frame),
limita a duracao por categoria, normaliza pico em -1 dBFS, fade-out curto, salva 48k estereo em
sfx/bank/<categoria>/<categoria>_NN_<id>.wav e registra tudo em sfx/LICENCAS.txt.
"""
import os
import subprocess
import urllib.request
import wave

import numpy as np

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "biblioteca", "sfx")
RAW = os.path.join(OUT, "raw")
BANK = os.path.join(OUT, "bank")
SR = 48000

# categoria -> (duracao maxima em s, modo de corte, [(id, nome)])
#   modo "head": comeca no transiente | "tail": pega o final que termina no pico (risers)
CATS = {
    "whoosh_s": (1.0, "head", [(1492, "cinematic whoosh fast transition"), (1491, "arrow whoosh"),
                               (1490, "fast whoosh transition"), (166, "fast small sweep transition"),
                               (175, "short transition sweep"), (3115, "fast transitions swoosh"),
                               (2608, "air zoom vacuum")]),
    "whoosh_l": (1.8, "head", [(1489, "air woosh"), (1474, "transition windy swoosh"),
                               (1465, "vacuum swoosh transition"), (1493, "swirling whoosh"),
                               (1168, "woosh wind")]),
    "pop": (0.6, "head", [(2364, "hard pop click"), (2354, "message pop alert"),
                          (3005, "explainer video pops whoosh light pop"), (2357, "bubble pop up alert"),
                          (2356, "dry pop up notification"), (2358, "long pop")]),
    "impact": (2.5, "head", [(1143, "cinematic whoosh deep impact"), (772, "quick zoom impact"),
                             (2908, "movie trailer epic impact"), (788, "big cinematic impact"),
                             (498, "deep heartbeat impact")]),
    "riser": (1.6, "tail", [(790, "cinematic trailer riser"), (1144, "short space stutter intro"),
                            (645, "cinematic synth riser")]),
    "ding": (1.6, "head", [(3109, "relaxing bell chime"), (600, "achievement bell"),
                           (2352, "magic glitter particles"), (2350, "magic sparkle whoosh")]),
    "cut": (0.8, "head", [(1133, "camera shutter click"), (1432, "camera digital shutter"),
                          (1530, "paper slide"), (2380, "paper quick movement")]),
}


def fetch(sid):
    os.makedirs(RAW, exist_ok=True)
    for ext, url in (("wav", f"https://assets.mixkit.co/active_storage/sfx/{sid}/{sid}.wav"),
                     ("mp3", f"https://assets.mixkit.co/active_storage/sfx/{sid}/{sid}-preview.mp3")):
        p = os.path.join(RAW, f"{sid}.{ext}")
        if os.path.exists(p) and os.path.getsize(p) > 1000:
            return p, url
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as r, open(p, "wb") as f:
                f.write(r.read())
            if os.path.getsize(p) > 1000:
                return p, url
        except Exception:
            if os.path.exists(p):
                os.remove(p)
    raise RuntimeError(f"falha ao baixar {sid}")


def decode(path):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.float32).reshape(-1, 2).copy()


def process(x, max_d, mode):
    env = np.abs(x).max(axis=1)
    thr = env.max() * 10 ** (-36 / 20)
    idx = np.nonzero(env > thr)[0]
    x = x[max(0, idx[0] - int(0.003 * SR)): idx[-1] + 1]
    n = int(max_d * SR)
    if len(x) > n:
        if mode == "tail":
            peak = int(np.argmax(np.abs(x).max(axis=1)))
            end = min(len(x), peak + int(0.05 * SR))
            x = x[max(0, end - n): end]
        else:
            x = x[:n]
    x = x / (np.abs(x).max() + 1e-9) * 10 ** (-1 / 20)
    f = min(len(x) // 4, int(0.04 * SR))
    x[-f:] *= np.linspace(1, 0, f)[:, None]
    if mode == "tail":
        fi = int(0.15 * SR)
        x[:fi] *= np.linspace(0, 1, fi)[:, None]
    return x


def save(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())


if __name__ == "__main__":
    lic = ["BANCO DE SFX — AD01 v4", "",
           "Fonte: Mixkit (https://mixkit.co/free-sound-effects/)",
           "Licenca: Mixkit Sound Effects Free License — uso comercial e pessoal gratuito, sem atribuicao obrigatoria.",
           "Termos: https://mixkit.co/license/#sfxFree", "",
           "Processamento: corte de silencio inicial, limite de duracao por categoria, pico -1 dBFS, fade-out 40ms.", ""]
    for cat, (max_d, mode, items) in CATS.items():
        d = os.path.join(BANK, cat)
        os.makedirs(d, exist_ok=True)
        lic.append(f"[{cat}]")
        for k, (sid, name) in enumerate(items, 1):
            src, url = fetch(sid)
            x = process(decode(src), max_d, mode)
            fn = f"{cat}_{k:02d}_{sid}.wav"
            save(os.path.join(d, fn), x)
            lic.append(f"  {fn:32s} {len(x) / SR:4.2f}s  '{name}'  {url}")
            print(cat, fn, f"{len(x) / SR:.2f}s")
        lic.append("")
    with open(os.path.join(OUT, "LICENCAS.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lic) + "\n")

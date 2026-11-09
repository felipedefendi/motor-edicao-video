"""Mapeia onde destaque grande / impacto de tela cheia cai sobre b-roll (para avisar o Felipe antes do render).

Uso: py -3.12 motor/mapa_texto_broll.py jobs/<job>     (depois de um teste ou render: le work/v8/plano_*.json e legenda_*.ass)
"""
import json
import os
import re
import sys

_var = os.environ.get("JOB_VARIANT", "").strip().lower()      # carro -> work/v8_carro
W8 = os.path.join(os.path.abspath(sys.argv[1]), "work", "v8" + ("_" + _var if _var else ""))


def secs(t):
    h, mi, s = t.split(":")
    return int(h) * 3600 + int(mi) * 60 + float(s)


for name in sorted(os.listdir(W8)):
    mm = re.match(r"plano_(\w+)\.json$", name)   # \w+ : versao pode ter mais de um caractere (ad02: C1, B2)
    if not mm:
        continue
    L = mm.group(1)
    plan = json.load(open(os.path.join(W8, name), encoding="utf-8"))
    br = [(b["de"], b["ate"], b["b"], b["modo"]) for b in plan["broll"]]
    big = {}
    for line in open(os.path.join(W8, f"legenda_{L}.ass"), encoding="utf-8"):
        if not (line.startswith("Dialogue: 3,") or line.startswith("Dialogue: 5,")):
            continue
        p = line.split(",", 9)
        kind = "IMPACTO" if p[0].endswith("5") else "destaque"
        key = (kind, p[2])
        a = secs(p[1])
        big.setdefault(key, [a, secs(p[2]), []])
        big[key][0] = min(big[key][0], a)
        big[key][2].append(re.sub(r"\{[^}]*\}", "", p[9].strip()))
    print(f"== {L}")
    for (kind, _), (a, b, txt) in sorted(big.items(), key=lambda x: x[1][0]):
        hits = [f"{k}({mo}) {max(a, x):.1f}-{min(b, y):.1f}" for x, y, k, mo in br if min(b, y) - max(a, x) > 0.15]
        if hits:
            print(f"  {a:6.1f}-{b:6.1f} {kind:8s} {' '.join(txt)[:40]:40s} -> {'; '.join(hits)}")

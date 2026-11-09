"""Ensaio da legenda v8 SEM renderizar: lista legenda comum, destaques (BIG) e janelas de impacto de uma versao.

Uso: py -3.12 motor/ensaio_legendas.py jobs/<job> A
Serve para conferir quebras, palavras soltas e atrasos em segundos, antes dos testes de 10s.
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import montar as m  # noqa: E402

m.load_job(sys.argv[1])
L = sys.argv[2].upper()
hook = "hook_" + L.lower()
tl, words, total = m.build_timeline([hook] + m.BODY)
hs = m.HOOK_SPLITS[L]
hook_end = sum(s["len"] for s in tl if s["clip"] == hook)
splits = [(m.phrase_window(words, hook, hs[0][1], total)[0], hook_end)] if hs else []   # hook sem b-roll = sem split
clips = {w["clip"] for w in words}
imps = [(m.find_phrase(words, it["clip"], it["phrase"]), it) for it in m.IMPACT8 if it["clip"] in clips]
sty = getattr(m, "HIGHLIGHT8_STYLE", {})
hls = [(m.find_phrase(words, c, p), sty.get((c, p), "hl")) for c, p in m.HIGHLIGHT if c in clips]
out = os.path.join(tempfile.gettempdir(), f"ensaio_{L}.ass")
blur, sfx = m.write_ass_v8(out, words, total, splits, imps, hls)
rows, imp = [], {}
for line in open(out, encoding="utf-8"):
    if not line.startswith("Dialogue:"):
        continue
    p = line.split(",", 9)
    txt = re.sub(r"\{[^}]*\}", "", p[9].strip()).replace("\\N", " / ")
    if p[0].endswith("1") and p[3] == "S":
        rows.append((p[1], p[2], "    ", txt))
    elif p[0].endswith("3"):
        rows.append((p[1], p[2], "BIG ", txt))
    elif p[0].endswith("5"):                      # impacto: 1 evento por palavra -> 1 linha por bloco
        imp.setdefault(p[2], [p[1], []])[1].append(txt)
rows += [(a, e, "IMP ", " ".join(ws)) for e, (a, ws) in imp.items()]
for a, e, k, txt in sorted(set(rows)):
    print(a, e, k, txt)
print(f"total {total:.1f}s | impactos (inicio do blur, fim): {[(round(a, 2), round(b, 2)) for a, b in blur]}")

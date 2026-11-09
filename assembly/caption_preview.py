"""Caption rehearsal WITHOUT rendering: lists the regular captions, the highlights (BIG) and the
full-screen emphasis windows of one version.

Usage: python assembly/caption_preview.py jobs/<job> A
Useful to check line breaks, stray words and delays in seconds before the 10-second test renders.
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assemble as m  # noqa: E402

m.load_job(sys.argv[1])
L = sys.argv[2].upper()
hook = "hook_" + L.lower()
tl, words, total = m.build_timeline([hook] + m.BODY)
hs = m.HOOK_SPLITS[L]
hook_end = sum(s["len"] for s in tl if s["clip"] == hook)
splits = [(m.phrase_window(words, hook, hs[0][1], total)[0], hook_end)] if hs else []   # hook without b-roll = no split
clips = {w["clip"] for w in words}
emphases = [(m.find_phrase(words, it["clip"], it["phrase"]), it) for it in m.EMPHASIS if it["clip"] in clips]
styles = getattr(m, "HIGHLIGHT_STYLE", {})
highlights = [(m.find_phrase(words, c, p), styles.get((c, p), "hl")) for c, p in m.HIGHLIGHT if c in clips]
out = os.path.join(tempfile.gettempdir(), f"caption_preview_{L}.ass")
blur, sfx = m.write_ass_centered(out, words, total, splits, emphases, highlights)
rows, emphasis_blocks = [], {}
for line in open(out, encoding="utf-8"):
    if not line.startswith("Dialogue:"):
        continue
    p = line.split(",", 9)
    txt = re.sub(r"\{[^}]*\}", "", p[9].strip()).replace("\\N", " / ")
    if p[0].endswith("1") and p[3] == "S":
        rows.append((p[1], p[2], "    ", txt))
    elif p[0].endswith("3"):
        rows.append((p[1], p[2], "BIG ", txt))
    elif p[0].endswith("5"):                      # emphasis: one event per word -> one row per block
        emphasis_blocks.setdefault(p[2], [p[1], []])[1].append(txt)
rows += [(a, e, "EMP ", " ".join(ws)) for e, (a, ws) in emphasis_blocks.items()]
for a, e, k, txt in sorted(set(rows)):
    print(a, e, k, txt)
print(f"total {total:.1f}s | emphasis windows (blur start, end): {[(round(a, 2), round(b, 2)) for a, b in blur]}")

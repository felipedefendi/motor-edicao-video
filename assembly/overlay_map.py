"""Maps where a big highlight or a full-screen emphasis lands on top of b-roll, to flag it before the render.

Usage: python assembly/overlay_map.py jobs/<job>     (after a test or render: reads work/<style>/plan_*.json and captions_*.ass)
"""
import json
import os
import re
import sys

_variant = os.environ.get("JOB_VARIANT", "").strip().lower()
WORK = os.path.join(os.path.abspath(sys.argv[1]), "work", "centered" + ("_" + _variant if _variant else ""))


def secs(t):
    h, mi, s = t.split(":")
    return int(h) * 3600 + int(mi) * 60 + float(s)


for name in sorted(os.listdir(WORK)):
    mm = re.match(r"plan_(\w+)\.json$", name)   # \w+ : a version id may have more than one character
    if not mm:
        continue
    L = mm.group(1)
    plan = json.load(open(os.path.join(WORK, name), encoding="utf-8"))
    br = [(b["from"], b["to"], b["key"], b["mode"]) for b in plan["broll"]]
    big = {}
    for line in open(os.path.join(WORK, f"captions_{L}.ass"), encoding="utf-8"):
        if not (line.startswith("Dialogue: 3,") or line.startswith("Dialogue: 5,")):
            continue
        p = line.split(",", 9)
        kind = "EMPHASIS" if p[0].endswith("5") else "highlight"
        key = (kind, p[2])
        a = secs(p[1])
        big.setdefault(key, [a, secs(p[2]), []])
        big[key][0] = min(big[key][0], a)
        big[key][2].append(re.sub(r"\{[^}]*\}", "", p[9].strip()))
    print(f"== {L}")
    for (kind, _), (a, b, txt) in sorted(big.items(), key=lambda x: x[1][0]):
        hits = [f"{k}({mo}) {max(a, x):.1f}-{min(b, y):.1f}" for x, y, k, mo in br if min(b, y) - max(a, x) > 0.15]
        if hits:
            print(f"  {a:6.1f}-{b:6.1f} {kind:9s} {' '.join(txt)[:40]:40s} -> {'; '.join(hits)}")

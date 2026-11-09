"""Assembly engine: cuts presenter clips by the real voice, lays b-roll, captions, emphasis typography and
sound effects, and renders with FFmpeg.

Usage:  python assembly/assemble.py jobs/<job> [A B C]
Test:   TEST_SECONDS=10 python assembly/assemble.py jobs/<job> A      (10-second render in jobs/<job>/work/<style>/)

Reads jobs/<job>/job_config.py (b-roll per phrase, emphasis, lip-sync coverage) and the shared library
(library/broll, library/sfx/bank, library/assets, library/fonts).

Caption styles, chosen by the job config:
  classic    - running caption at the bottom + headline cards (CALLOUTS) and kinetic phrases (KINETIC_PHRASES)
  condensed  - every spoken word in condensed upper case, highlighted phrases in yellow (HIGHLIGHT + SFX_CONDENSED)
  centered   - one caption at a time in the centre, small highlights and full-screen emphasis (EMPHASIS)
"""
import json
import os
import random
import re
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kinetic  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "library")
BR = os.path.join(LIB, "broll")
BANK = os.path.join(LIB, "sfx", "bank")
ASSETS = os.path.join(LIB, "assets")


def load_job(job_dir):
    """Loads jobs/<job>/job_config.py and injects its UPPERCASE constants into this module."""
    import importlib.util
    global JOB, AV, TR, OUT, WORK, PREVIOUS_PLAN
    JOB = os.path.abspath(job_dir)
    AV, OUT = os.path.join(JOB, "avatar"), os.path.join(JOB, "output")
    TR = os.path.join(AV, "transcripts")
    WORK, PREVIOUS_PLAN = os.path.join(JOB, "work", "condensed"), os.path.join(JOB, "work", "previous")
    # JOB_VARIANT=<name> -> job_config_<name>.py, work/centered_<name>, lipsync_clips_<name>.json, output with _<NAME>
    suffix = "_" + VARIANT if VARIANT else ""
    spec = importlib.util.spec_from_file_location("job_config", os.path.join(JOB, f"job_config{suffix}.py"))
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    globals().update({k: v for k, v in vars(cfg).items() if k.isupper()})
    if is_centered():
        WORK = os.path.join(JOB, "work", "centered" + suffix)
        globals()["BROLL"] = {**BROLL, **globals().get("BROLL_CENTERED", {})}
    os.makedirs(WORK, exist_ok=True)


VARIANT = os.environ.get("JOB_VARIANT", "").strip().lower()


def clip_file(c, ext):
    """mp4 / transcript of a clip; CLIP_DIR (job_config) = {clip: subfolder of avatar/} for takes of another variant."""
    sub = globals().get("CLIP_DIR", {}).get(c)
    if ext == "json":
        return os.path.join(AV, sub, "transcripts", c + ".json") if sub else os.path.join(TR, c + ".json")
    return os.path.join(AV, sub, c + ".mp4") if sub else os.path.join(AV, c + ".mp4")


def lipsync_file():
    return os.path.join(AV, f"lipsync_clips{'_' + VARIANT if VARIANT else ''}.json")


def is_centered():
    """centered style when the job defines EMPHASIS (ENGINE_STYLE=condensed forces the condensed style)."""
    return bool(globals().get("EMPHASIS")) and os.environ.get("ENGINE_STYLE") != "condensed"


W, H, PH, FPS, SR = 720, 1280, 640, 30, 48000
COLOR = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"
GAP_MAX, GAP_PAD, TAIL = 0.50, 0.15, 0.30
END_HOLD = 0.6                                         # slack at the end of the video (last frame held + silence)
PUNCH, SPLIT_ZOOM = 1.08, 1.12
COVER_PAD = 0.15
MAX_FACELESS = 7.0

COLORS = {"Y": "&H0000D4FF", "R": "&H003A4BFF", "W": "&H00FFFFFF", "G": "&H006BE82E"}  # BGR, solid
CAP_FONT, CAP_SIZE = "Segoe UI Semibold", 54          # running caption (clean)
HEAD_FONT, HEAD_SCALEX = "Bahnschrift", 80            # condensed (Bahnschrift Bold compressed)
LEAD_FONT = "Georgia"                                 # small italic line above the headline
Y_CAP, YS_CAP = 1075, 640                             # running caption: normal / split
Y_HEAD, YS_HEAD = 1035, 640                           # headline: normal / split
CHUNK_MAX, CHUNK_CHARS = 4, 22
LETTER_MS = 32                                        # interval of the letter-by-letter "typing"
# lean SFX: few events, the same files repeated on purpose
SFX_FILES = {"whoosh": "whoosh_s/whoosh_s_01_1492.wav", "swoosh": "whoosh_l/whoosh_l_01_1489.wav",
             "impact": "impact/impact_01_1143.wav", "pop": "pop/pop_03_3005.wav",
             "riser": "riser/riser_01_790.wav", "ding": "ding/ding_01_3109.wav",
             "heart": "impact/impact_05_498.wav", "money": "money/money_01_1999.wav",
             "air": "whoosh_l/whoosh_l_01_1489.wav"}
COLORS_KINETIC = {"G": "&H006BE82E", "R": "&H003B3BFF", "Y": "&H0000D4FF", "W": "&H00FFFFFF"}   # BGR solid
# condensed style: condensed caption over all speech; pure yellow, larger highlight
CAPC_FONT, CAPC_FILE, CAPC_FS = "League Gothic", "LeagueGothic.ttf", 118
CAPC_CHARW = 0.26                                     # average upper-case width in League Gothic / font size
HLC_COLOR, HLC_SCALE = "&H0000E6FF&", 1.45            # #FFE600
CHUNKC_WORDS, CHUNKC_CHARS = 3, 18
SFX_FILES.update({"looming": "condensed/looming.wav", "flash": "condensed/flash.wav",
                  "clock": "condensed/clock.wav", "cymbal": "condensed/cymbal.wav"})
# centered style: Montserrat caption centred, one at a time; small yellow highlight / lockup;
# full-screen emphasis (blur + darken, word by word, colour by meaning) only on the job's EMPHASIS entries
CAPM_FAM, CAPM_FILE, CAPM_FS = "Montserrat Thin", "Montserrat-Bold.ttf", 54   # internal family name of the Fontsource Bold (+ \b1)
LG_FAM, LG_FILE = "League Gothic", "LeagueGothic.ttf"
RATIO = {CAPM_FILE: 0.6346, LG_FILE: 0.7663}         # libass / Pillow width (calibrated on a 720x1280 canvas)
PALETTE = {"Y": "FFE600", "G": "00E35B", "R": "FF2B2B", "W": "FFFFFF"}   # yellow numbers, green positive, red negative
Y_CENTER = 640                                       # centre of the frame (on split = the seam)
UNITS = {"hours", "seconds", "years", "weeks", "days", "minutes", "million", "views"}
FUNCTION_WORDS = {"a", "an", "the", "to", "and", "than", "less", "of", "in", "on", "at", "for", "with", "from", "that",
                  "my", "her", "your", "his", "their", "it", "is", "i", "you", "she", "we", "but", "or", "so", "because",
                  "will", "just", "when", "more", "this", "these", "are", "was", "had", "have", "has", "who", "what", "me"}
SFX_FILES.update({k: f"centered/{k}.wav" for k in ("pop02", "click05", "whoosh01", "whoosh04", "swipe01", "swipe02")})


def norm(s):
    return re.sub(r"[^a-z0-9']", "", s.lower())


def run(cmd, **kw):
    subprocess.run(cmd, check=True, **kw)


def duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def load_words(name):
    with open(clip_file(name, "json"), encoding="utf-8") as f:
        j = json.load(f)
    out = []
    fix = {k.lower(): v for k, v in globals().get("WORD_FIX", {}).items()}   # job_config: {"heard": "Written"} (transcriber -> script)
    for w in (w for seg in j["segments"] for w in seg["words"]):
        t = w["word"].strip()
        t = globals().get("TOKEN_FIX", {}).get((name, t), t)   # job_config: {(clip, "names,"): "names"} punctuation not in the script
        if out and re.fullmatch(r"[,%.]\d*%?", t) and out[-1]["w"][-1:].isdigit():   # "86" ",000" -> "86,000" | "97" "%" -> "97%"
            out[-1]["w"] += t
            out[-1]["e"] = float(w["end"])
            continue
        m_ = re.fullmatch(r"([^A-Za-z0-9']*)([A-Za-z0-9']+)([^A-Za-z0-9']*)", t)
        if m_ and m_.group(2).lower() in fix:
            t = m_.group(1) + fix[m_.group(2).lower()] + m_.group(3)
        # WORD_JOIN (job_config): {"two words": "OneWord"} — the transcriber split one word of the script in two
        pair = (norm(out[-1]["w"]) + " " + norm(t)) if out else ""
        if pair in globals().get("WORD_JOIN", {}):
            out[-1]["w"] = re.sub(r"[A-Za-z0-9']+", "", out[-1]["w"]) + WORD_JOIN[pair] + re.sub(r"^[^.,!?;:]*", "", t)
            out[-1]["e"] = float(w["end"])
            continue
        out.append({"w": t, "s": float(w["start"]), "e": float(w["end"])})
    return out


def asset_path(name):
    return os.path.join(ASSETS, name[1:] + ".mp4") if name.startswith("@") else os.path.join(BR, name)


# ---------------- timeline ----------------

_env = {}


def voice_env(path):
    """voice level (dB RMS in 10 ms windows) — the transcriber sometimes marks the start of a word late,
    and a pause cut would eat the beginning of the word."""
    if path not in _env:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                           capture_output=True, check=True)
        x = np.frombuffer(r.stdout, dtype="<i2").astype(np.float32) / 32768
        n = len(x) // 160
        rms = np.sqrt((x[:n * 160].reshape(n, 160) ** 2).mean(1)) + 1e-9
        _env[path] = 20 * np.log10(rms)
    return _env[path]


def voice_edge(path, t, direction, limit=0.6, thr=-50.0):
    """walks from t while there is voice (> thr dB) up to 'limit' s, crossing micro-pauses < 80 ms (plosives);
    returns the real edge of the speech."""
    env = voice_env(path)
    i = int(t * 100)
    last, quiet = i, 0
    for k in range(int(limit * 100)):
        j = i + direction * k
        if j < 0 or j >= len(env):
            break
        if env[j] >= thr:
            last, quiet = j, 0
        else:
            quiet += 1
            if quiet >= 8:
                break
    return (last + (1 if direction > 0 else 0)) / 100


def build_timeline(clips):
    """Cuts follow the real voice: never the last word of a clip or the first of the next."""
    timeline, words, t = [], [], 0.0
    for ci, c in enumerate(clips):
        path = clip_file(c, "mp4")
        ws, dur = load_words(c), duration(path)
        segs, start = [], 0.0
        for a, b in zip(ws, ws[1:]):
            if b["s"] - a["e"] > GAP_MAX:
                end_a = max(a["e"], voice_edge(path, a["e"], +1)) + GAP_PAD
                start_b = min(b["s"], voice_edge(path, b["s"], -1)) - GAP_PAD
                if start_b - end_a < 0.05:              # the voice fills the pause: do not cut
                    continue
                segs.append((start, end_a))
                start = start_b
        last_clip = ci == len(clips) - 1
        end = dur if last_clip else min(dur, max(ws[-1]["e"], voice_edge(path, ws[-1]["e"], +1)) + TAIL)
        segs.append((start, end))
        for k, (s0, s1) in enumerate(segs):
            hold = END_HOLD if last_clip and k == len(segs) - 1 else 0.0   # slack at the end of the video (held frame)
            timeline.append({"clip": c, "path": path, "src": s0, "len": s1 - s0, "start": t, "hold": hold})
            for w in ws:
                if s0 <= w["s"] < s1:
                    words.append({"w": w["w"], "s": t + w["s"] - s0, "e": t + min(w["e"], s1) - s0, "clip": c})
            t += s1 - s0 + hold
    return timeline, words, t


def clip_to_timeline(timeline, clip, a, b):
    """Interval [a,b] in clip time -> list of intervals on the timeline (respecting the pause cuts)."""
    out = []
    for seg in timeline:
        if seg["clip"] != clip:
            continue
        s0, s1 = seg["src"], seg["src"] + seg["len"]
        lo, hi = max(a, s0), min(b, s1)
        if hi > lo:
            out.append((seg["start"] + lo - s0, seg["start"] + hi - s0))
    return out


def find_phrase(words, clip, phrase):
    toks = [norm(x) for x in phrase.split()]
    cw = [i for i, w in enumerate(words) if w["clip"] == clip]
    for k in range(len(cw) - len(toks) + 1):
        idx = cw[k:k + len(toks)]
        if [norm(words[i]["w"]) for i in idx] == toks:
            return idx
    raise ValueError(f"phrase '{phrase}' not found in {clip}")


def phrase_window(words, clip, phrase, total):
    idx = find_phrase(words, clip, phrase)
    a = words[idx[0]]["s"] - 0.04
    last = idx[-1]
    if last + 1 < len(words) and words[last + 1]["clip"] == clip:
        b = words[last + 1]["s"] - 0.04
    else:
        b = min(total, words[last]["e"] + 0.20)
    return max(0.0, a), b, idx


def coverage(intervals, overlays):
    """fraction of each interval covered by full-screen overlays."""
    res = []
    for a, b in intervals:
        cov = 0.0
        for o in overlays:
            if o["mode"] in ("full", "cover"):
                cov += max(0.0, min(b, o["b"]) - max(a, o["a"]))
        res.append(min(1.0, cov / max(1e-6, b - a)))
    return res


# ---------------- SFX ----------------

class SfxBank:
    def __init__(self, seed=7):
        self.files, self.pos = {}, {}
        rnd = random.Random(seed)
        for cat in sorted(os.listdir(BANK)):
            fs = sorted(os.path.join(BANK, cat, f) for f in os.listdir(os.path.join(BANK, cat)) if f.endswith(".wav"))
            rnd.shuffle(fs)
            self.files[cat], self.pos[cat] = fs, 0
        self.cache = {}

    def next(self, cat):                       # round-robin: never repeats the same file back to back
        fs = self.files[cat]
        f = fs[self.pos[cat] % len(fs)]
        self.pos[cat] += 1
        return f

    def read(self, path):
        if path not in self.cache:
            with wave.open(path) as w:
                x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768
                self.cache[path] = x.reshape(-1, 2)
        return self.cache[path]


def build_sfx_track(bank, events, total, path):
    track = np.zeros((int((total + 3) * SR), 2), dtype=np.float32)
    used = []
    for t, cat, gain in events:
        f = os.path.join(BANK, SFX_FILES[cat]) if cat in SFX_FILES else bank.next(cat)
        x = bank.read(f)
        i = int(max(0.0, t) * SR)
        seg = x[: len(track) - i] * 10 ** (gain / 20)
        track[i:i + len(seg)] += seg
        used.append((round(t, 2), cat, os.path.basename(f), gain))
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(track, -1, 1) * 32767).astype("<i2").tobytes())
    return used


# ---------------- classic captions ----------------

def ass_time(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def esc(s):
    return s.replace("{", "").replace("}", "")


def write_ass_classic(path, words, total, split_windows, callouts, extra_events=(), extra_cov=()):
    """Classic captions. callouts: [(a, b, idx, lead, BIG, kind, colour)] kind = head | card."""
    head = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: C,{CAP_FONT},{CAP_SIZE},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,"
        "0,0,0,0,100,100,0,0,1,1.6,1.5,5,30,30,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    ev = []
    in_split = lambda t: any(a <= t < b for a, b in split_windows)
    T = ass_time

    def typed(text, color, t0=0):
        """'typed' text letter by letter: each letter goes from translucent grey to the solid colour."""
        out, k = [], 0
        for ch in text:
            if ch == "\n":
                out.append("\\N")
                continue
            if ch == " ":
                out.append(" ")
                continue
            t = t0 + k * LETTER_MS
            out.append(f"{{\\1c&H8C8C8C&\\alpha&HFF&\\t({t},{t + 70},\\alpha&H00&)\\t({t + 40},{t + 140},\\1c{color})}}"
                       f"{esc(ch)}")
            k += 1
        return "".join(out), t0 + k * LETTER_MS + 140

    covered = list(extra_cov)
    for k, (a, b, idx, lead, big, kind, color) in enumerate(callouts):
        b = max(b, a + 1.0)
        covered.append((a, b))
        col = COLORS.get(color, COLORS["W"])
        lines = big.split("\n")
        longest = max(len(x) for x in lines)
        if kind == "card":
            size = int(min(250, 640 / (0.38 * max(4, longest))))      # fills ~90% of the width
            txt, _ = typed(big, col)
            fx = f"\\fn{HEAD_FONT}\\b1\\fs{size}\\fscx{HEAD_SCALEX}\\bord0\\shad0"
            ev.append(f"Dialogue: 4,{T(a)},{T(b)},C,,0,0,0,,{{\\pos({W // 2},{H // 2}){fx}\\fad(0,60)}}{txt}")
            continue
        # headline over the video: small italic lead + big condensed upright word(s)
        sp = in_split(a)
        y = YS_HEAD if sp else Y_HEAD
        size = int(min(150, 560 / (0.38 * max(4, longest))))
        nl = len(lines)
        hb = size * 0.92 * nl
        fx = f"\\fn{HEAD_FONT}\\b1\\fs{size}\\fscx{HEAD_SCALEX}"
        t_big = 0
        if lead:
            ly = int(y - hb / 2 - 26)
            ev.append(f"Dialogue: 2,{T(a)},{T(b)},C,,0,0,0,,{{\\pos({W // 2},{ly})\\fn{LEAD_FONT}\\i1\\fs40\\bord0"
                      f"\\shad2\\4a&H40&\\fad(160,120)}}{esc(lead)}")
            t_big = 120
        txt, _ = typed(big, col, t_big)
        # dark halo behind only (invisible fill), enters and leaves together with the text
        ev.append(f"Dialogue: 2,{T(a)},{T(b)},C,,0,0,0,,{{\\pos({W // 2},{y}){fx}\\1a&HFF&\\3c&H000000&\\3a&H90&"
                  f"\\bord12\\blur14\\shad0\\fad(220,120)}}{esc(big).replace(chr(10), '\\N')}")
        ev.append(f"Dialogue: 3,{T(a)},{T(b)},C,,0,0,0,,{{\\pos({W // 2},{y}){fx}\\bord0\\shad3\\4a&H60&"
                  f"\\fad(0,120)}}{txt}")

    # running caption: words appear as they are spoken; only keywords in colour
    in_cov = lambda t: any(a <= t < b for a, b in covered)
    cap = [w for w in words if not in_cov(w["s"])]
    chunks, cur = [], []
    for i, w in enumerate(cap):
        cur.append(w)
        nxt = cap[i + 1] if i + 1 < len(cap) else None
        chars = sum(len(x["w"]) + 1 for x in cur) + (len(nxt["w"]) if nxt else 0)
        if (len(cur) >= CHUNK_MAX or chars > CHUNK_CHARS or re.search(r"[.,!?]$", w["w"]) or nxt is None
                or nxt["s"] - w["e"] > 0.35 or in_cov((w["e"] + nxt["s"]) / 2)
                or in_split(nxt["s"]) != in_split(cur[0]["s"])):
            chunks.append(cur)
            cur = []
    for ch in chunks:
        s0 = ch[0]["s"]
        nxt_start = next((w["s"] for w in words if w["s"] > ch[-1]["s"]), total)
        end = min(ch[-1]["e"] + 0.30, nxt_start)
        y = YS_CAP if in_split(s0) else Y_CAP
        parts = []
        for w in ch:
            t = int((w["s"] - s0) * 1000)
            kw = norm(w["w"]) in KEYWORDS
            c = f"\\1c{COLORS['Y']}" if kw else ""
            parts.append(f"{{{c}\\alpha&HFF&\\t({t},{t + 120},\\alpha&H00&)}}{esc(w['w'])}{{\\1c&H00FFFFFF&}}")
        ev.append(f"Dialogue: 1,{T(s0)},{T(end)},C,,0,0,0,,{{\\pos({W // 2},{y})\\fad(0,80)}}" + " ".join(parts))

    ev += list(extra_events)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(head + ev) + "\n")


def write_ass_condensed(path, words, total, split_windows, hl):
    """Condensed captions: every spoken word appears (UPPER CASE, condensed, upright, word by word).
    hl = indices of highlighted words -> their own block, yellow, larger, with a short pop."""
    head = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: C,{CAPC_FONT},{CAPC_FS},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,0,0,5,30,30,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    T = ass_time
    in_split = lambda t: any(a <= t < b for a, b in split_windows)
    chunks, cur = [], []
    for i, w in enumerate(words):
        cur.append(i)
        nxt = i + 1 if i + 1 < len(words) else None
        txt = " ".join(words[k]["w"] for k in cur)
        if (nxt is None or (i in hl) != (nxt in hl) or words[nxt]["clip"] != w["clip"]
                or (i not in hl and (len(cur) >= CHUNKC_WORDS or len(txt) + 1 + len(words[nxt]["w"]) > CHUNKC_CHARS
                                     or re.search(r"[.,!?]$", w["w"])))
                or words[nxt]["s"] - w["e"] > 0.35 or in_split(words[nxt]["s"]) != in_split(words[cur[0]]["s"])):
            chunks.append(cur)
            cur = []
    ev = []
    for n_, ch in enumerate(chunks):
        s0 = words[ch[0]]["s"]
        nxt_start = words[chunks[n_ + 1][0]]["s"] if n_ + 1 < len(chunks) else total
        is_hl = ch[0] in hl
        end = min(words[ch[-1]]["e"] + (0.55 if is_hl else 0.30), nxt_start)
        y = YS_CAP if in_split(s0) else Y_CAP - 15
        toks = [re.sub(r"[.,;:]+$", "", words[k]["w"]).upper() for k in ch]
        lines = [list(range(len(toks)))]
        fs = CAPC_FS
        if is_hl:
            chars = len(" ".join(toks))
            if chars > 14 and len(toks) > 1:            # break into 2 balanced lines
                best = min(range(1, len(toks)), key=lambda c: abs(len(" ".join(toks[:c])) - len(" ".join(toks[c:]))))
                lines = [list(range(best)), list(range(best, len(toks)))]
            longest = max(len(" ".join(toks[k] for k in l)) for l in lines)
            fs = int(min(CAPC_FS * HLC_SCALE, 640 / (CAPC_CHARW * longest)))
        fill, halo = [], []
        for li, line in enumerate(lines):
            for j, k in enumerate(line):
                t = max(0, int((words[ch[k]]["s"] - s0) * 1000))
                tok = esc(toks[k])
                sep = " " if j < len(line) - 1 else ("\\N" if li < len(lines) - 1 else "")
                fill.append(f"{{\\alpha&HFF&\\t({t},{t + 90},\\alpha&H00&)}}{tok}{sep}")
                halo.append(f"{{\\3a&HFF&\\t({t},{t + 90},\\3a&H70&)}}{tok}{sep}")
        col = HLC_COLOR if is_hl else "&H00FFFFFF&"
        pop = "\\fscx110\\fscy110\\t(0,120,\\fscx100\\fscy100)" if is_hl else ""
        base = f"\\an5\\pos({W // 2},{y})\\fs{fs}{pop}\\fad(0,80)"
        ev.append(f"Dialogue: 1,{T(s0)},{T(end)},C,,0,0,0,,{{{base}\\1a&HFF&\\bord14\\blur16\\3c&H000000&}}"
                  + "".join(halo))
        ev.append(f"Dialogue: 2,{T(s0)},{T(end)},C,,0,0,0,,{{{base}\\1c{col}\\bord0\\shad0}}" + "".join(fill))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(head + ev) + "\n")


# ---------------- centered captions ----------------
_fonts = {}


def text_width(file, text, fs):
    """width of the text in libass (calibrated Pillow)."""
    from PIL import ImageFont
    if file not in _fonts:
        _fonts[file] = ImageFont.truetype(os.path.join(LIB, "fonts", file), 100)
    return _fonts[file].getlength(text) * fs / 100 * RATIO[file]


def bgr(hexrgb):
    return f"&H00{hexrgb[4:6]}{hexrgb[2:4]}{hexrgb[0:2]}&".upper()


def write_ass_centered(path, words, total, split_windows, emphases, highlights):
    """Centered captions. emphases = [(indices, EMPHASIS cfg)], highlights = [(indices, style)].
    One caption at a time in the centre; small highlight = start of the sentence in the regular caption +
    strong part big below; emphasis = full screen word by word. Returns (blur windows, sounds
    [(t, cat, gain, priority)])."""
    T = ass_time
    fs = CAPM_FS
    halo = "\\1a&HFF&\\bord8\\blur10\\3c&H000000&\\3a&H80&\\shad0"
    in_split = lambda t: any(a - 1e-3 <= t < b - 1e-3 for a, b in split_windows)    # tolerance for float edges
    used, units = set(), []
    for idx, cfg in emphases:
        units.append({"kind": "emp", "idx": idx, "lead": [], "cfg": cfg})
        used |= set(idx)
    for idx, style in highlights:
        if used & set(idx):
            continue
        lead, k = [], idx[0] - 1               # start of the same sentence (up to 4 words; stops at punctuation)
        while (k >= 0 and k not in used and words[k]["clip"] == words[idx[0]]["clip"] and len(lead) < 5
               and not re.search(r"[.!?,]$", words[k]["w"]) and words[k + 1]["s"] - words[k]["e"] <= 0.35):
            lead.insert(0, k)
            k -= 1
        if len(lead) > 4:                      # long sentence: only the last words (from a function word if any)
            lead = lead[-3:]
            k = next((j for j in range(1, len(lead) - 1) if norm(words[lead[j]]["w"]) in FUNCTION_WORDS), 0)
            lead = lead[k:]
        units.append({"kind": style, "idx": idx, "lead": lead})
        used |= set(idx) | set(lead)

    def split_sense(seg):
        """long sentence -> parts by unit of meaning: cut at commas, never after a function word
        nor between a number and its unit; balanced parts, up to ~40 characters (2 lines)."""
        txt = " ".join(words[k]["w"] for k in seg)
        if (len(txt) <= 40 and len(seg) <= 8) or len(seg) < 2:
            return [seg]
        toks = [words[k]["w"] for k in seg]

        def cost(c):
            a, b = " ".join(toks[:c]), " ".join(toks[c:])
            p = abs(len(a) - len(b)) / 10
            p += 4 if norm(toks[c - 1]) in FUNCTION_WORDS else 0
            p += 5 if re.search(r"\d", toks[c - 1]) else 0
            p -= 3 if toks[c - 1].endswith(",") else 0
            return p
        c = min(range(1, len(seg)), key=cost)
        return split_sense(seg[:c]) + split_sense(seg[c:])

    cur = []                                   # regular caption: whole sentence, up to 2 lines
    for i, w in enumerate(words):
        if i in used:
            continue
        cur.append(i)
        nx = i + 1
        if (nx >= len(words) or nx in used or words[nx]["clip"] != w["clip"] or words[nx]["s"] - w["e"] > 0.35
                or in_split(words[nx]["s"]) != in_split(words[cur[0]]["s"]) or re.search(r"[.!?]$", w["w"])):
            for part in split_sense(cur):
                units.append({"kind": "n", "idx": part, "lead": []})
            cur = []
    for u in units:
        u["first"] = (u["lead"] or u["idx"])[0]
        u["s0"] = words[u["first"]]["s"]
    units.sort(key=lambda u: u["s0"])
    prev_end = -1.0
    for n_, u in enumerate(units):
        nxt = units[n_ + 1] if n_ + 1 < len(units) else None
        last = u["idx"][-1]
        u["start"] = max(u["s0"], prev_end + 0.02)
        if u["kind"] == "n":
            end = min(words[last]["e"] + 0.6, nxt["s0"] - 0.02 if nxt else total)
        else:                                   # highlight holds on screen; the next caption waits (delay <= 0.9s)
            hold = 1.1 if u["kind"] == "emp" else 1.4
            ref = words[last]["s"] if u["kind"] == "emp" else words[u["idx"][0]]["s"]
            end = max(words[last]["e"] + 0.35, ref + hold)
            if nxt:     # only holds over a weak connective ("and…"); otherwise the next caption is delayed at most 0.25s
                weak = norm(words[nxt["first"]]["w"]) in {"and", "but", "so", "or", "then"}
                end = min(end, nxt["s0"] + ((0.9 if weak else 0.25) if nxt["kind"] == "n" else -0.02))
        u["end"] = min(total, max(end, u["start"] + 0.5))
        prev_end = u["end"]

    ev, blur, sfx = [], [], []
    for u in units:
        s, e, idx = u["start"], u["end"], u["idx"]
        if u["kind"] == "n":
            toks = [words[i]["w"] for i in idx]
            num = [k for k, t in enumerate(toks) if re.search(r"\d", t)]
            yel = {k + 1 for k in num if k + 1 < len(toks) and norm(toks[k + 1]) in UNITS}
            wid = lambda a, b: sum(text_width(CAPM_FILE, toks[k], fs) * (1.8 if k in num else 1) for k in range(a, b)) \
                + text_width(CAPM_FILE, " ", fs) * (b - a - 1)
            lines = [(0, len(toks))]
            if wid(0, len(toks)) > 600 and len(toks) > 1:
                c = min(range(1, len(toks)), key=lambda c: (0 if toks[c - 1].endswith(",") else 1,
                                                             abs(wid(0, c) - wid(c, len(toks)))))
                lines = [(0, c), (c, len(toks))]

            def fmt(k, hl):
                t = esc(toks[k])
                if k in num:
                    return f"{{\\fs{int(fs * 1.8)}{'' if hl else chr(92) + '1c' + bgr(PALETTE['Y'])}}}{t}{{\\fs{fs}\\1c&H00FFFFFF&}}"
                if k in yel and not hl:
                    return f"{{\\1c{bgr(PALETTE['Y'])}}}{t}{{\\1c&H00FFFFFF&}}"
                return t
            for L, extra, hl in ((0, halo, True), (1, "", False)):
                tx = "\\N".join(" ".join(fmt(k, hl) for k in range(a, b)) for a, b in lines)
                ev.append(f"Dialogue: {L},{T(s)},{T(e)},S,,0,0,0,,{{\\an5\\pos({W // 2},{Y_CENTER}){extra}\\fad(120,90)}}{tx}")
            if num:
                sfx.append((words[idx[num[0]]]["s"], "pop02", -18, 1))
        elif u["kind"] in ("hl", "lock"):
            lead = " ".join(words[i]["w"] for i in u["lead"])
            big = re.sub(r"[.,;:]+$", "", " ".join(words[i]["w"] for i in idx)).upper()
            if u["kind"] == "lock":                  # lockup: Montserrat Bold upper case
                bl, bfs = [big], 96
                bh = bfs * 1.0
            else:                                    # big yellow (League Gothic), 2 lines if long
                toks = big.split()
                bl = [big]
                if len(big) > 14 and len(toks) > 1:
                    c = min(range(1, len(toks)), key=lambda c: abs(len(" ".join(toks[:c])) - len(" ".join(toks[c:]))))
                    bl = [" ".join(toks[:c]), " ".join(toks[c:])]
                bfs = int(min(170, 640 / max(text_width(LG_FILE, l, 100) for l in bl) * 100))
                bh = bfs * 0.86 * (len(bl) - 1) + bfs * 0.75
            # compact block centred in the frame; may cross the split seam (words far apart read badly)
            lh = 58 if lead else 0
            top = Y_CENTER + globals().get("HL_DY", 0) - (lh + bh) / 2   # HL_DY (job_config): lowers the highlight when the face is large
            if lead:
                for L, extra in ((0, halo), (1, "")):
                    ev.append(f"Dialogue: {L},{T(s)},{T(e)},S,,0,0,0,,{{\\an5\\pos({W // 2},{top + lh / 2:.0f}){extra}\\fad(120,90)}}{esc(lead)}")
            t_big = max(s, words[idx[0]]["s"])
            big_halo = halo.replace("bord8", "bord12").replace("blur10", "blur16")
            pitch = bfs * 0.86            # each line in its own event: \N uses the tall League Gothic leading
            for li, l in enumerate(bl):
                yl = top + lh + bfs * 0.375 + li * pitch
                if u["kind"] == "lock":
                    sty, fx = "S", f"\\b1\\fs{bfs}\\move({W // 2},{yl + 12:.0f},{W // 2},{yl:.0f},0,160)"
                else:
                    sty, fx = "L", (f"\\fs{bfs}\\pos({W // 2},{yl:.0f})\\fscx80\\fscy80\\t(0,90,\\fscx106\\fscy106)"
                                    f"\\t(90,170,\\fscx100\\fscy100)")
                for L, extra in ((2, big_halo), (3, f"\\1c{bgr(PALETTE['Y'])}\\shad3")):
                    ev.append(f"Dialogue: {L},{T(t_big)},{T(e)},{sty},,0,0,0,,{{\\an5{fx}{extra}\\fad(80,90)}}{esc(l)}")
            sfx.append((t_big, "pop02" if re.search(r"\d", big) else "click05", -18, 1))
        else:                                        # full-screen emphasis
            cfg = u["cfg"]
            up = [re.sub(r",$", "", words[i]["w"]).upper() for i in idx]
            keys = [norm(words[i]["w"]) for i in idx]
            colours, big_words = cfg.get("colours", {}), cfg.get("big", set())
            lines, k0 = [], 0
            for c in cfg.get("lines", [len(up)]):
                lines.append(list(range(k0, min(k0 + c, len(up)))))
                k0 += c
            lfs = []
            for line in lines:
                fit = 650 / text_width(LG_FILE, " ".join(up[k] for k in line), 100) * 100
                strong = any(keys[k] in colours or keys[k] in big_words for k in line)
                single_number = len(line) == 1 and re.search(r"\d", up[line[0]])     # a number alone on its line: giant
                lfs.append(min(fit, 340 if (strong and single_number) else 250 if strong else 165))
            sc = min(1.0, 640 / (0.80 * sum(lfs)))
            lfs = [int(f * sc) for f in lfs]
            hs = [0.80 * f for f in lfs]
            ytop = 505 - sum(hs) / 2
            for li, line in enumerate(lines):
                f_ = lfs[li]
                sp = text_width(LG_FILE, " ", f_)
                x = W / 2 - text_width(LG_FILE, " ".join(up[k] for k in line), f_) / 2
                for k in line:
                    wk = text_width(LG_FILE, up[k], f_)
                    cx, cy = x + wk / 2, ytop + sum(hs[:li]) + hs[li] / 2
                    x += wk + sp
                    t0 = max(s, words[idx[k]]["s"])
                    col = bgr(PALETTE[colours.get(keys[k], "W")])
                    base = (f"\\an5\\pos({cx:.0f},{cy:.0f})\\fs{f_}\\fscx55\\fscy55\\t(0,110,\\fscx112\\fscy112)"
                            f"\\t(110,200,\\fscx100\\fscy100)\\fad(40,140)")
                    ev.append(f"Dialogue: 4,{T(t0)},{T(e)},L,,0,0,0,,{{{base}\\1a&HFF&\\bord14\\blur18\\3c&H000000&\\3a&H60&}}{esc(up[k])}")
                    ev.append(f"Dialogue: 5,{T(t0)},{T(e)},L,,0,0,0,,{{{base}\\1c{col}\\shad3\\4c&H000000&\\4a&H40&}}{esc(up[k])}")
            blur.append((max(0.0, s - 0.15), e))
            t1 = words[idx[0]]["s"]
            for dt, cat, db in cfg.get("sfx", []):
                sfx.append((t1 + dt, cat, db + 1, 0))
    head = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: S,{CAPM_FAM},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,0,2.5,5,0,0,0,1",
        f"Style: L,{LG_FAM},120,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(head + ev) + "\n")
    return blur, sfx


# ---------------- render ----------------

REPORT = []


def build(letter, bank):
    hook = "hook_" + letter.lower()
    timeline, words, total = build_timeline([hook] + BODY)
    hook_end = sum(s["len"] for s in timeline if s["clip"] == hook)

    ov = []   # dicts: key, a, b, mode (split|full|cover)
    hs = HOOK_SPLITS[letter]
    starts = [phrase_window(words, hook, ph, total)[0] for _, ph in hs]
    for i, (key, _) in enumerate(hs):
        ov.append({"key": key, "a": starts[i], "b": starts[i + 1] if i + 1 < len(hs) else hook_end, "mode": "split"})
    splits = [(starts[0], hook_end)] if starts else []   # hook without b-roll (HOOK_SPLITS empty) = no split panel
    for key, clip, ph in BODY_BROLL + EXTRA_BODY_BROLL.get(letter, []):
        try:
            a, b, _ = phrase_window(words, clip, ph, total)
        except ValueError as e:
            print("WARNING:", e)
            continue
        # BODY_SPLIT: body b-roll in the bottom panel with the face on top, instead of full screen
        ov.append({"key": key, "a": a, "b": max(b, a + 1.8), "mode": "split" if globals().get("BODY_SPLIT") else "full"})

    # broken lip-sync -> coverage (priority over regular b-roll)
    with open(lipsync_file(), encoding="utf-8") as f:
        lips = json.load(f)
    broken = []
    for clip, r in lips.items():
        if not r or clip not in [s["clip"] for s in timeline]:
            continue
        for a, b in r["broken"]:
            for ta, tb in clip_to_timeline(timeline, clip, a, b):
                broken.append((clip, ta, tb))
    for clip, ta, tb in broken:
        a, b = ta - COVER_PAD, tb + COVER_PAD
        cov = {**COVER, **globals().get("COVER_CENTERED", {})} if is_centered() else COVER
        keys = cov.get(clip, globals().get("COVER_DEFAULT", []))
        if not keys:                           # covered by a blurred emphasis instead (EMPHASIS), or nothing declared
            continue
        parts = keys if b - a > 3.0 and len(keys) > 1 else keys[:1]
        step = (b - a) / len(parts)
        for i, k in enumerate(parts):
            ov.append({"key": k, "a": a + i * step, "b": a + (i + 1) * step, "mode": "cover"})

    # resolve overlaps: cover wins
    ov.sort(key=lambda o: (o["a"], o["mode"] != "cover"))
    res = []
    for o in ov:
        for p in res:
            if p["b"] > o["a"] and o["b"] > p["a"]:
                if o["mode"] == "cover" and p["mode"] != "cover":
                    p["b"] = o["a"]
                elif p["mode"] == "cover":
                    o["a"] = max(o["a"], p["b"])
                else:
                    p["b"] = o["a"]
        if o["b"] - o["a"] > 0.25:
            res.append(o)
    res = [o for o in res if o["b"] - o["a"] > 0.25]
    res.sort(key=lambda o: o["a"])

    # no faceless block longer than MAX_FACELESS: shortens the last regular b-roll of the block
    blk = []
    for o in res + [None]:
        if o is not None and o["mode"] != "split" and blk and o["a"] - blk[-1]["b"] < 0.1:
            blk.append(o)
            continue
        if blk and blk[-1]["b"] - blk[0]["a"] > MAX_FACELESS:
            for p in reversed(blk):
                if p["mode"] == "full":
                    p["b"] = max(p["a"] + 1.0, blk[0]["a"] + MAX_FACELESS - (blk[-1]["b"] - p["b"]))
                    break
        blk = [o] if o is not None and o["mode"] != "split" else []
    overlays = res
    if globals().get("BODY_SPLIT"):    # face panel on top only where there is b-roll below (after cuts/coverage)
        splits += [(o["a"], o["b"]) for o in overlays if o["mode"] == "split" and o["a"] >= hook_end - 1e-3]

    # no b-roll file from the UNIQUE_BROLL_PREFIX group repeated in the same video
    prefix = globals().get("UNIQUE_BROLL_PREFIX", "product")
    unique_files = [BROLL[o["key"]][0] for o in overlays if o["key"].startswith(prefix)]
    assert len(unique_files) == len(set(unique_files)), f"repeated '{prefix}' file in {letter}: {unique_files}"

    # lip-sync report: coverage before (previous plan, if any) / after
    iv = [(ta, tb) for _, ta, tb in broken]
    previous = []
    pp = os.path.join(PREVIOUS_PLAN, f"plan_{letter}.json")
    if os.path.exists(pp):
        with open(pp, encoding="utf-8") as f:
            previous = [{"a": o["from"], "b": o["to"], "mode": o["mode"]} for o in json.load(f)["broll"]]
    before, after = coverage(iv, previous), coverage(iv, overlays)
    REPORT.append((letter, broken, before, after))

    # kinetic phrases: LITERAL phrase word by word (kinetic.py), optional scrim, optional icon
    callouts, k_events, k_cov, scrims, icons, k_sfx = [], [], [], [], [], []
    highlights = globals().get("HIGHLIGHT")
    clips_here = {w["clip"] for w in words}
    hl_idx = set()
    for clip, ph in (highlights or []):
        if clip in clips_here:
            hl_idx.update(find_phrase(words, clip, ph))
    kinetic_phrases = None if highlights else globals().get("KINETIC_PHRASES")
    if kinetic_phrases:
        found = []
        for it in kinetic_phrases:
            if not any(w["clip"] == it["clip"] for w in words):
                continue
            try:
                a, b, idx = phrase_window(words, it["clip"], it["phrase"], total)
            except ValueError as e:
                print("WARNING:", e)
                continue
            found.append((a, b, idx, it))
        found.sort(key=lambda x: x[0])
        for n_, (a, b, idx, it) in enumerate(found):
            nxt = found[n_ + 1][0] if n_ + 1 < len(found) else total
            last_t = words[idx[-1]]["s"]
            end = min(max(b + 0.35, last_t + it.get("hold", 1.1)), nxt - 0.05, total)   # last word stays >= hold
            toks = kinetic.tokens_from_words([words[i] for i in idx])
            times = [words[i]["s"] for i in idx]
            colors = {k: COLORS_KINETIC[c] for k, t in enumerate(toks) for w_, c in it.get("accent", {}).items()
                      if t.strip("?!") in w_.upper().split()}
            big = {k: f for k, t in enumerate(toks) for w_, f in it.get("big", {}).items() if t == w_.upper()}
            icon = None
            if it.get("icon"):
                aft = next((k for k, t in enumerate(toks) if t == it["icon"]["after"].upper()), len(toks) - 1)
                icon = {"after": aft, "w": it["icon"].get("w", 0.9), "emoji": it["icon"]["emoji"]}
            sp = any(sa <= a < sb for sa, sb in splits)
            kind = it.get("kind", "over")
            cy = 640 if (kind == "scrim" or sp) else it.get("y", 1000)
            ev6, ipos = kinetic.phrase_events(toks, times, end, W // 2, cy, 640 if kind == "scrim" else 600,
                                              150 if kind == "scrim" else 116, colors, big=big,
                                              breaks=it.get("breaks"), icon=icon,
                                              max_lines=4 if kind == "scrim" else 3)
            k_events += ev6
            k_cov.append((a, end))
            if kind == "scrim":
                scrims.append((a - 0.05, end))
            if icon and ipos:
                x0, y0, f_i = ipos
                isz = int(f_i * 0.95)
                mov = kinetic.render_icon(icon["emoji"], isz, os.path.join(WORK, f"icon_{ord(icon['emoji'][0]):x}_{isz}.mov"))
                icons.append((mov, times[icon["after"]] + 0.05, end, int(x0), int(y0 - (isz + 8) / 2)))
            if it.get("sfx"):
                hit = next((times[k] for k, t in enumerate(toks) if t == it.get("sfx_at", "").upper()), a)
                k_sfx.append((hit, it["sfx"], it.get("sfx_db", -15)))
                if it.get("riser"):
                    k_sfx.append((hit - 0.85, "riser", -17))
    elif not highlights:
        for clip, ph, lead, bigt, kind, color in CALLOUTS:
            if not any(w["clip"] == clip for w in words):
                continue
            try:
                a, b, idx = phrase_window(words, clip, ph, total)
            except ValueError as e:
                print("WARNING:", e)
                continue
            callouts.append((a, b, idx, lead, bigt, kind, color))
        callouts.sort(key=lambda x: x[0])
    cards = [(x[0], max(x[1], x[0] + 1.0)) for x in callouts if x[5] == "card"]

    os.makedirs(WORK, exist_ok=True)
    ass_name = f"captions_{letter}.ass"
    first_split = next((o for o in overlays if o["mode"] == "split" and o["a"] < hook_end), None)   # flash only on the hook's split entry
    blur_windows = []
    if is_centered():
        emphases = [(find_phrase(words, it["clip"], it["phrase"]), it) for it in EMPHASIS if it["clip"] in clips_here]
        styles = globals().get("HIGHLIGHT_STYLE", {})
        hls = [(find_phrase(words, clip, ph), styles.get((clip, ph), "hl")) for clip, ph in (highlights or []) if clip in clips_here]
        blur_windows, cand = write_ass_centered(os.path.join(WORK, ass_name), words, total, splits, emphases, hls)
        # emphasis with b-roll behind it (full, cover or split panel): no blur/darkening, so the b-roll and the
        # presenter stay visible; blur only where the background is the presenter alone. If b-roll covers only
        # PART of the window, the blur stays on the presenter-only stretch.
        nb = []
        for a, b in blur_windows:
            segs = [(a, b)]
            for o in overlays:
                nxt = []
                for sa, sb in segs:
                    if min(sb, o["b"]) - max(sa, o["a"]) > 0.15:
                        if o["a"] - sa > 0.35:
                            nxt.append((sa, o["a"]))
                        if sb - o["b"] > 0.35:
                            nxt.append((o["b"], sb))
                    else:
                        nxt.append((sa, sb))
                segs = nxt
            nb += segs
        blur_windows = nb
        # the lip-sync report counts the emphasis blur as coverage
        REPORT[-1] = (letter, broken, before, coverage(iv, overlays + [{"a": a, "b": b, "mode": "cover"} for a, b in blur_windows]))
        # centered-style sounds: looming at the open, flash on the split entry, emphasis sounds (priority 0) and
        # POP 02 / CLICK 05 for small highlights only when no other sound is within 3 s (lean SFX)
        ev = [(0.0, "looming", -15)]
        if first_split:
            ev.append((first_split["a"] - 0.03, "flash", -12))
        for t, cat, g, pri in sorted(cand, key=lambda x: (x[3], x[0])):
            if pri == 0 or all(abs(t - t2) > 3.0 for t2, _, _ in ev):
                ev.append((t, cat, g))
        # BROLL_SFX (job_config): soft whoosh/swipe on each body b-roll entry, alternating the bank sounds,
        # only with clearance from other sounds
        bs = globals().get("BROLL_SFX")
        if bs:
            k = 0
            for o in overlays:
                if o["a"] >= hook_end - 1e-3 and all(abs(o["a"] - t2) > bs["gap"] for t2, _, _ in ev):
                    ev.append((o["a"] - 0.12, bs["cats"][k % len(bs["cats"])], bs["db"]))
                    k += 1
    elif highlights:
        write_ass_condensed(os.path.join(WORK, ass_name), words, total, splits, hl_idx)
        # condensed-style SFX: looming at the open, flash on the split entry and on SFX_CONDENSED entries,
        # clock on time references, cymbal before the closing call
        ev = [(0.0, "looming", -17)]
        if first_split:
            ev.append((first_split["a"] - 0.03, "flash", -13))
        for clip, ph, cat, db in SFX_CONDENSED:
            if clip not in clips_here:
                continue
            t0 = words[find_phrase(words, clip, ph)[0]]["s"]
            ev.append((t0 - 0.03, cat, db))
            if ph.startswith("tap"):
                ev.append((t0 - 1.74, "cymbal", -16))
    else:
        write_ass_classic(os.path.join(WORK, ass_name), words, total, splits, callouts, k_events, k_cov)
        # lean SFX: opening, split entry, cards, 1-2 red headlines in the hook, closing call
        ev = [(0.0, "impact", -10), (0.0, "whoosh", -15)]
        if first_split:
            ev.append((first_split["a"], "whoosh", -17))
        for a, b in cards:
            ev.append((a - 0.05, "swoosh", -14))
        hook_red = [x for x in callouts if x[2] and words[x[2][0]]["clip"] == hook and x[5] == "head" and x[6] == "R"]
        for x in hook_red[:2]:
            ev.append((x[0], "pop", -17))
        for x in callouts:
            if x[4].lower().startswith("tap"):
                ev.append((x[0] - 0.85, "riser", -15))
                ev.append((x[0], "impact", -12))
        ev += k_sfx
        ev += [(a, "air", -19) for a, _ in scrims]
    ev.sort()
    flashes = [t + 0.03 for t, cat, _ in ev if cat == "flash"]
    fdir = os.path.join(WORK, "fonts")
    os.makedirs(fdir, exist_ok=True)
    import shutil
    for ff in ([CAPM_FILE, LG_FILE] if is_centered() else [CAPC_FILE] if highlights else []):
        if not os.path.exists(os.path.join(fdir, ff)):
            shutil.copy(os.path.join(LIB, "fonts", ff), fdir)
    sfx_path = os.path.join(WORK, f"sfx_{letter}.wav")
    used = build_sfx_track(bank, ev, total, sfx_path)
    grad = os.path.join(ASSETS, "gradient.png")

    # ffmpeg
    cmd = ["ffmpeg", "-v", "error", "-stats", "-y"]
    for seg in timeline:
        cmd += ["-ss", f"{seg['src']:.3f}", "-t", f"{seg['len']:.3f}", "-i", seg["path"]]
    n = len(timeline)
    for o in overlays:
        f_, src, _, ext_ = BROLL[o["key"]]
        sl = ext_.get("slow", 1.0)      # slow (job_config): slow motion; reads only (dur / slow) of the source to stay in the clean window
        cmd += ["-ss", f"{src:.3f}", "-t", f"{(o['b'] - o['a']) / sl + (0.5 if sl == 1.0 else 0.05):.3f}", "-i", asset_path(f_)]
    i_sfx = n + len(overlays)
    cmd += ["-i", sfx_path, "-i", grad]
    i_grad = i_sfx + 1
    scrim_png = os.path.join(ASSETS, "scrim.png")
    if not os.path.exists(scrim_png):
        Image_ = __import__("PIL.Image", fromlist=["Image"])
        Image_.new("RGBA", (W, H), (6, 6, 10, 150)).save(scrim_png)
    i_scr = i_grad + 1
    if scrims:                      # a single input, repeated in the filter (a PNG with -loop 1 stalls ffmpeg)
        cmd += ["-i", scrim_png]
    i_ico = i_scr + (1 if scrims else 0)
    for mov, a, b, x, y in icons:
        cmd += ["-t", f"{b - a:.3f}", "-i", mov]

    fc = []
    for i in range(n):
        z = PUNCH if i % 2 else 1.0
        sw = int(round(W * z / 2) * 2)
        sh = int(round(sw * 736 / 400 / 2) * 2)
        chain = f"[{i}:v]{COLOR},scale={sw}:{sh},crop={W}:{H}:(iw-{W})/2:(ih-{H})*0.35,fps={FPS},setsar=1"
        if i == 0:
            chain += (f",scale=w='trunc({W}*(1+0.22*pow(max(0\\,1-t/0.45)\\,2))/2)*2':h=-2:eval=frame,"
                      f"crop={W}:{H},fade=in:st=0:d=0.22:color=white")
        hold = timeline[i].get("hold", 0.0)
        hv = f",tpad=stop_mode=clone:stop_duration={hold:.3f}" if hold else ""
        ha = f",afade=t=out:st={timeline[i]['len'] - 0.15:.3f}:d=0.15,apad=pad_dur={hold:.3f}" if hold else ""
        fc.append(chain + ",setsar=1,setpts=PTS-STARTPTS" + hv + f"[v{i}]")
        fc.append(f"[{i}:a]aresample={SR},aformat=channel_layouts=stereo,asetpts=PTS-STARTPTS{ha}[a{i}]")
    fc.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[base][voice]")

    en = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in splits) or "0"
    cw, ch = int(W / SPLIT_ZOOM) // 2 * 2, int(PH / SPLIT_ZOOM) // 2 * 2
    fc.append("[base]split[b0][b1]")
    # SPLIT_TOP_Y (job_config): where the top panel starts in the presenter frame (raise it when the face sits low)
    fc.append(f"[b1]crop={cw}:{ch}:({W}-{cw})/2:{globals().get('SPLIT_TOP_Y', 24)},scale={W}:{PH}[top]")
    fc.append(f"[b0][top]overlay=0:0:enable='{en}'[s0]")
    last = "s0"
    for k, o in enumerate(overlays):
        f_, src, anc, ext = BROLL[o["key"]]
        th = PH if o["mode"] == "split" else H
        zx = ext.get("zoom", 1.0)
        tw, tth = int(W * zx) // 2 * 2, int(th * zx) // 2 * 2
        blur = f",gblur=sigma={ext['blur']}" if ext.get("blur") else ""
        nfr = max(2, int((o["b"] - o["a"] + 0.5) * FPS))
        pre = f",crop={ext['precrop']}" if ext.get("precrop") else ""   # removes black bars from the source
        slow = f",setpts={ext['slow']}*PTS" if ext.get("slow") else ""
        chain = (f"{COLOR}{pre},scale={tw}:{tth}:force_original_aspect_ratio=increase,crop={W}:{th}:(iw-{W})/2:(ih-{th})*{anc}"
                 f"{blur}{slow},fps={FPS},setsar=1,tpad=stop_mode=clone:stop_duration=3,"
                 f"scale={W * 2}:{th * 2},zoompan=z='1+0.06*on/{nfr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                 f":d=1:s={W}x{th}:fps={FPS},setpts=PTS-STARTPTS+{o['a']:.3f}/TB")
        fc.append(f"[{n + k}:v]{chain}[o{k}]")
        y = PH if o["mode"] == "split" else 0
        fc.append(f"[{last}][o{k}]overlay=0:{y}:eof_action=pass:enable='between(t,{o['a']:.3f},{o['b']:.3f})'[x{k}]")
        last = f"x{k}"
    fc.append(f"[{i_grad}:v]format=rgba,loop=loop=-1:size=1:start=0,fps={FPS}[g]")
    fc.append(f"[{last}][g]overlay=0:0:shortest=1[gr0]")
    lastg = "gr0"
    if scrims:
        fc.append(f"[{i_scr}:v]format=rgba,split={len(scrims)}" + "".join(f"[scs{k}]" for k in range(len(scrims))))
    for k, (a, b) in enumerate(scrims):
        d = b - a
        fc.append(f"[scs{k}]loop=loop={int(d * FPS) + 2}:size=1:start=0,setpts=N/{FPS}/TB,trim=0:{d:.3f},fade=in:st=0:d=0.18:alpha=1,fade=out:st={max(0, d - 0.2):.3f}:d=0.2:alpha=1,"
                  f"setpts=PTS-STARTPTS+{a:.3f}/TB[sc{k}]")
        fc.append(f"[{lastg}][sc{k}]overlay=0:0:eof_action=pass[gs{k}]")
        lastg = f"gs{k}"
    for k, (mov, a, b, x, y) in enumerate(icons):
        fc.append(f"[{i_ico + k}:v]format=rgba,fade=out:st={max(0, b - a - 0.16):.3f}:d=0.16:alpha=1,"
                  f"setpts=PTS-STARTPTS+{a:.3f}/TB[ic{k}]")
        fc.append(f"[{lastg}][ic{k}]overlay={x}:{y}:eof_action=pass[gi{k}]")
        lastg = f"gi{k}"
    fc.append(f"[{lastg}]null[gr]")
    if blur_windows:       # emphasis: the video itself strongly blurred + darkened only inside the window (trim = cheap)
        fc.append(f"[gr]split={len(blur_windows) + 1}[gq]" + "".join(f"[gc{k}]" for k in range(len(blur_windows))))
        lq = "gq"
        for k, (a, b) in enumerate(blur_windows):
            fc.append(f"[gc{k}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,gblur=sigma=26,"
                      f"eq=brightness=-0.20:saturation=0.85,format=yuva420p,fade=t=in:st=0:d=0.15:alpha=1,"
                      f"fade=t=out:st={max(0, b - a - 0.15):.3f}:d=0.15:alpha=1,setpts=PTS+{a:.3f}/TB[gb{k}]")
            fc.append(f"[{lq}][gb{k}]overlay=0:0:eof_action=pass[gz{k}]")
            lq = f"gz{k}"
        fc.append(f"[{lq}]format=yuv420p[grb]")
    glab = "grb" if blur_windows else "gr"
    boxes = "".join(f"drawbox=color=0x0b0b0d@0.94:t=fill:enable='between(t,{a:.3f},{b:.3f})',"
                    f"drawbox=color=white@0.55:t=fill:enable='between(t,{b:.3f},{b + 0.07:.3f})',"
                    for a, b in cards)
    boxes += "".join(f"drawbox=color=white@0.8:t=fill:enable='between(t,{t:.3f},{t + 0.067:.3f})',"
                     f"drawbox=color=0xFFE9C0@0.3:t=fill:enable='between(t,{t + 0.067:.3f},{t + 0.15:.3f})',"
                     for t in flashes)
    fc.append(f"[{glab}]{boxes}ass={ass_name}:fontsdir=fonts,trim=0:{total:.3f},format=yuv420p[vout]")
    fc.append(f"[{i_sfx}:a]aresample={SR}[sx]")
    fc.append("[voice][sx]amix=inputs=2:duration=first:normalize=0,"
              "loudnorm=I=-14:TP=-1.5:LRA=9,aresample=48000[aout]")

    var = "_" + VARIANT.upper() if VARIANT else ""
    style = "centered" if is_centered() else "condensed" if highlights else "classic"
    out = os.path.join(OUT, f"{PREFIX}_HOOK_{letter}{var}_720p_{style}.mp4")
    limit = float(os.environ.get("TEST_SECONDS", 0)) or total
    if os.environ.get("TEST_SECONDS"):
        out = os.path.join(WORK, f"test_{letter}.mp4")
    frm = ["-ss", os.environ["TEST_FROM"]] if os.environ.get("TEST_FROM") else []
    # filter graph in a file: with many b-rolls the command line exceeds the Windows limit
    fc_name = f"filter_{letter}.txt"
    with open(os.path.join(WORK, fc_name), "w", encoding="utf-8") as f:
        f.write(";\n".join(fc))
    cmd += ["-/filter_complex", fc_name, "-map", "[vout]", "-map", "[aout]"] + frm + ["-t", f"{limit:.3f}",
            "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out]
    run(cmd, cwd=WORK)

    plan = {"version": letter, "duration": round(total, 2),
            "broll": [{"key": o["key"], "file": BROLL[o["key"]][0], "from": round(o["a"], 2), "to": round(o["b"], 2),
                       "mode": o["mode"]} for o in overlays],
            "emphases": len(k_cov) or len(callouts), "scrims": len(scrims), "icons": len(icons),
            "sfx": [{"t": u[0], "cat": u[1], "file": u[2], "db": u[3]} for u in used]}
    with open(os.path.join(WORK, f"plan_{letter}.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    print(f"{letter}: {total:.1f}s | b-rolls {len(overlays)} | emphases {len(k_cov) or len(callouts)} (scrims {len(scrims)}, icons {len(icons)}) | sfx {len(used)}")


def write_report():
    lines = [f"LIP-SYNC REPORT — {PREFIX}", "",
             "Detection: lipsync.py — head tracking by template + aligned mouth motion at 15 fps,",
             "active speech = transcriber words; broken = speech with a still mouth (< 38% of the median) for > 0.4 s.", ""]
    for letter, broken, before, after in REPORT:
        lines.append(f"VERSION {letter}")
        for (clip, a, b), x, y in zip(broken, before, after):
            m = lambda t: f"{int(t // 60)}:{t % 60:05.2f}"
            lines.append(f"  {clip:7s} {m(a)} - {m(b)}  ({b - a:.2f}s)   before: {x * 100:5.1f}% covered   "
                         f"after: {y * 100:5.1f}% covered")
        lines.append("")
    partial = os.environ.get("TEST_SECONDS") or len(REPORT) < len(VERSIONS)   # a test/partial run does not overwrite the official report
    name = f"lipsync_report{'_' + VARIANT if VARIANT else ''}.txt"
    with open(os.path.join(WORK if partial else OUT, name), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python assembly/assemble.py jobs/<job> [A B C]")
    load_job(sys.argv[1])
    bank = SfxBank(seed=7)
    for v in (sys.argv[2:] or VERSIONS):
        build(v.upper(), bank)
    write_report()

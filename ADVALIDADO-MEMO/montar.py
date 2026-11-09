"""Motor de montagem ADVALIDADO-MEMO (padrao v5: impacto estilo @migs.visuals + SFX enxuto).

Uso:   python motor/montar.py jobs/<job> [A B C]
Teste: V7_TEST=10 python motor/montar.py jobs/<job> A      (render de 10s em jobs/<job>/work/v7/)

Le jobs/<job>/job_config.py (b-roll por frase, enfases, cobertura de lip-sync) e usa a biblioteca
compartilhada (biblioteca/broll, biblioteca/sfx/bank, biblioteca/assets). Detalhes do padrao: SKILL.md.
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

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # .../ADVALIDADO-MEMO
LIB = os.path.join(SKILL, "biblioteca")
BR = os.path.join(LIB, "broll")
BANK = os.path.join(LIB, "sfx", "bank")
ASSETS = os.path.join(LIB, "assets")


def load_job(job_dir):
    """Carrega jobs/<job>/job_config.py e injeta as constantes MAIUSCULAS neste modulo."""
    import importlib.util
    global JOB, AV, TR, OUT, WORK, V3PLAN
    JOB = os.path.abspath(job_dir)
    AV, OUT = os.path.join(JOB, "avatar"), os.path.join(JOB, "entrega")
    TR = os.path.join(AV, "transcricoes")
    WORK, V3PLAN = os.path.join(JOB, "work", "v7"), os.path.join(JOB, "work", "v5")
    # JOB_VARIANT=carro -> job_config_carro.py, work/v8_carro, lipsync_clips_carro.json, entrega com _CARRO (nao toca a principal)
    sfx = "_" + VARIANT if VARIANT else ""
    spec = importlib.util.spec_from_file_location("job_config", os.path.join(JOB, f"job_config{sfx}.py"))
    cfg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cfg)
    globals().update({k: v for k, v in vars(cfg).items() if k.isupper()})
    if is_v8():
        WORK = os.path.join(JOB, "work", "v8" + sfx)
        globals()["BROLL"] = {**BROLL, **globals().get("BROLL8", {})}
    os.makedirs(WORK, exist_ok=True)


VARIANT = os.environ.get("JOB_VARIANT", "").strip().lower()


def clip_file(c, ext):
    """mp4 / transcricao do clipe; CLIP_DIR (job_config) = {clip: subpasta de avatar/} para takes de outra variacao."""
    sub = globals().get("CLIP_DIR", {}).get(c)
    if ext == "json":
        return os.path.join(AV, sub, "transcricoes", c + ".json") if sub else os.path.join(TR, c + ".json")
    return os.path.join(AV, sub, c + ".mp4") if sub else os.path.join(AV, c + ".mp4")


def lipsync_file():
    return os.path.join(AV, f"lipsync_clips{'_' + VARIANT if VARIANT else ''}.json")


def is_v8():
    """padrao v8 quando o job tem IMPACT8 (MOTOR_V=7 forca a v7)."""
    return bool(globals().get("IMPACT8")) and os.environ.get("MOTOR_V") != "7"


W, H, PH, FPS, SR = 720, 1280, 640, 30, 48000
FIX = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"
GAP_MAX, GAP_PAD, TAIL = 0.50, 0.15, 0.30
END_HOLD = 0.6                                         # folga no fim do video (ultimo quadro parado + silencio)
PUNCH, SPLIT_ZOOM = 1.08, 1.12
COVER_PAD = 0.15
MAX_FACELESS = 7.0

COLORS = {"Y": "&H0000D4FF", "R": "&H003A4BFF", "W": "&H00FFFFFF", "G": "&H006BE82E"}  # BGR, solidos
CAP_FONT, CAP_SIZE = "Segoe UI Semibold", 54          # legenda corrida (limpa, estilo referencia)
HEAD_FONT, HEAD_SCALEX = "Bahnschrift", 80            # condensada (Bahnschrift Bold comprimida ~ Bebas Neue)
LEAD_FONT = "Georgia"                                 # linha pequena em italico acima da manchete
Y_CAP, YS_CAP = 1075, 640                             # legenda corrida: normal / split
Y_HEAD, YS_HEAD = 1035, 640                           # manchete: normal / split
CHUNK_MAX, CHUNK_CHARS = 4, 22
LETTER_MS = 32                                        # intervalo do "digitado" letra a letra
# SFX enxuto e coerente: poucos eventos, mesmos arquivos repetidos de proposito
SFX_FILES = {"whoosh": "whoosh_s/whoosh_s_01_1492.wav", "swoosh": "whoosh_l/whoosh_l_01_1489.wav",
             "impact": "impact/impact_01_1143.wav", "pop": "pop/pop_03_3005.wav",
             "riser": "riser/riser_01_790.wav", "ding": "ding/ding_01_3109.wav",
             "heart": "impact/impact_05_498.wav", "money": "money/money_01_1999.wav",
             "air": "whoosh_l/whoosh_l_01_1489.wav"}
COLORS6 = {"G": "&H006BE82E", "R": "&H003B3BFF", "Y": "&H0000D4FF", "W": "&H00FFFFFF"}   # BGR solidos
# v7: legenda condensada (referencia Dreamina) em toda a fala; destaque amarelo puro e maior
CAP7_FONT, CAP7_FILE, CAP7_FS = "League Gothic", "LeagueGothic.ttf", 118
CAP7_CHARW = 0.26                                     # largura media da maiuscula em League Gothic / fs
HL7_COLOR, HL7_SCALE = "&H0000E6FF&", 1.45            # #FFE600
CHUNK7_WORDS, CHUNK7_CHARS = 3, 18
SFX_FILES.update({"looming": "v7/looming.wav", "flash": "v7/flash.wav", "clock": "v7/clock.wav",
                  "cymbal": "v7/cymbal.wav"})
# v8 (demos v8 / D4 aprovada 15/10/2026): legenda Montserrat centralizada, uma por vez; destaque pequeno amarelo/lockup;
# impacto de tela cheia (blur + escurece, palavra a palavra, cor por sentido) so nos IMPACT8 do job
CAP8_FAM, CAP8_FILE, CAP8_FS = "Montserrat Thin", "Montserrat-Bold.ttf", 54   # familia interna do Bold do Fontsource (+ \b1)
LG8_FAM, LG8_FILE = "League Gothic", "LeagueGothic.ttf"
RATIO8 = {CAP8_FILE: 0.6346, LG8_FILE: 0.7663}       # largura libass / Pillow (calibrado em canvas 720x1280)
COR8 = {"Y": "FFE600", "G": "00E35B", "R": "FF2B2B", "W": "FFFFFF"}   # amarelo numero/prova, verde transformacao, vermelho dor
Y8 = 640                                             # centro do quadro (no split = costura)
UNITS8 = {"hours", "seconds", "years", "weeks", "days", "minutes", "million", "views"}
FW8 = {"a", "an", "the", "to", "and", "than", "less", "of", "in", "on", "at", "for", "with", "from", "that", "my", "her",
       "your", "his", "their", "it", "is", "i", "you", "she", "we", "but", "or", "so", "because", "will", "just", "when",
       "more", "this", "these", "are", "was", "had", "have", "has", "who", "what", "me"}
SFX_FILES.update({k: f"v8/{k}.wav" for k in ("pop02", "click05", "whoosh01", "whoosh04", "swipe01", "swipe02")})


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
    fix = {k.lower(): v for k, v in globals().get("WORD_FIX", {}).items()}   # job_config: {"vix": "Vicks"} (Whisper -> copy)
    for w in (w for seg in j["segments"] for w in seg["words"]):
        t = w["word"].strip()
        t = globals().get("TOKEN_FIX", {}).get((name, t), t)   # job_config: {(clip, "names,"): "names"} pontuacao fora da copy
        if out and re.fullmatch(r"[,%.]\d*%?", t) and out[-1]["w"][-1:].isdigit():   # "86" ",000" -> "86,000" | "97" "%" -> "97%"
            out[-1]["w"] += t
            out[-1]["e"] = float(w["end"])
            continue
        m_ = re.fullmatch(r"([^A-Za-z0-9']*)([A-Za-z0-9']+)([^A-Za-z0-9']*)", t)
        if m_ and m_.group(2).lower() in fix:
            t = m_.group(1) + fix[m_.group(2).lower()] + m_.group(3)
        # WORD_JOIN (job_config): {"vapor rub": "VapoRub"} — Whisper partiu uma palavra da copy em duas
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
    """nivel da voz (dB RMS em janelas de 10 ms) — o Whisper as vezes marca o inicio da palavra atrasado
    (hook_b: "Doctors" falado em 7.15s, marcado 7.40s) e o corte de pausa comia o comeco da palavra."""
    if path not in _env:
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                           capture_output=True, check=True)
        x = np.frombuffer(r.stdout, dtype="<i2").astype(np.float32) / 32768
        n = len(x) // 160
        rms = np.sqrt((x[:n * 160].reshape(n, 160) ** 2).mean(1)) + 1e-9
        _env[path] = 20 * np.log10(rms)
    return _env[path]


def voice_edge(path, t, direction, limit=0.6, thr=-50.0):
    """anda de t enquanto ha voz (> thr dB) ate 'limit' s, atravessando micro-pausas < 80 ms (oclusiva do "D");
    devolve a borda real da fala."""
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
    """Cortes seguem a voz real (Felipe, v8: "cortando a ultima palavra ou a primeira", "live" cortado no fim)."""
    timeline, words, t = [], [], 0.0
    for ci, c in enumerate(clips):
        path = clip_file(c, "mp4")
        ws, dur = load_words(c), duration(path)
        segs, start = [], 0.0
        for a, b in zip(ws, ws[1:]):
            if b["s"] - a["e"] > GAP_MAX:
                end_a = max(a["e"], voice_edge(path, a["e"], +1)) + GAP_PAD
                start_b = min(b["s"], voice_edge(path, b["s"], -1)) - GAP_PAD
                if start_b - end_a < 0.05:              # a voz ocupa a pausa: nao corta
                    continue
                segs.append((start, end_a))
                start = start_b
        last_clip = ci == len(clips) - 1
        end = dur if last_clip else min(dur, max(ws[-1]["e"], voice_edge(path, ws[-1]["e"], +1)) + TAIL)
        segs.append((start, end))
        for k, (s0, s1) in enumerate(segs):
            hold = END_HOLD if last_clip and k == len(segs) - 1 else 0.0   # folga no fim do video (quadro parado)
            timeline.append({"clip": c, "path": path, "src": s0, "len": s1 - s0, "start": t, "hold": hold})
            for w in ws:
                if s0 <= w["s"] < s1:
                    words.append({"w": w["w"], "s": t + w["s"] - s0, "e": t + min(w["e"], s1) - s0, "clip": c})
            t += s1 - s0 + hold
    return timeline, words, t


def clip_to_timeline(timeline, clip, a, b):
    """Intervalo [a,b] em tempo do clipe -> lista de intervalos na timeline (respeita os cortes de pausa)."""
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
    raise ValueError(f"frase '{phrase}' nao encontrada em {clip}")


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
    """fracao de cada intervalo coberta por overlays full-screen."""
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

    def next(self, cat):                       # round-robin: nunca repete o mesmo arquivo em seguida
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


# ---------------- legenda solida ----------------

def ass_time(t):
    t = max(0.0, t)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


def esc(s):
    return s.replace("{", "").replace("}", "")


def write_ass(path, words, total, split_windows, impacts, extra_events=(), extra_cov=()):
    """Legenda v5. impacts: [(a, b, idx, lead, BIG, kind, cor)] kind = head | card."""
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
        """texto 'digitado' letra a letra: cada letra entra de cinza translucido para a cor solida."""
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
    for k, (a, b, idx, lead, big, kind, color) in enumerate(impacts):
        b = max(b, a + 1.0)
        covered.append((a, b))
        col = COLORS.get(color, COLORS["W"])
        lines = big.split("\n")
        longest = max(len(x) for x in lines)
        if kind == "card":
            size = int(min(250, 640 / (0.38 * max(4, longest))))      # ocupa ~90% da largura (como a referencia)
            txt, _ = typed(big, col)
            fx = f"\\fn{HEAD_FONT}\\b1\\fs{size}\\fscx{HEAD_SCALEX}\\bord0\\shad0"
            ev.append(f"Dialogue: 4,{T(a)},{T(b)},C,,0,0,0,,{{\\pos({W // 2},{H // 2}){fx}\\fad(0,60)}}{txt}")
            continue
        # manchete sobre o video: lead em italico pequeno + palavra(s) condensadas grandes, retas
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
        # halo escuro so por tras (fill invisivel), entra junto e sai junto
        ev.append(f"Dialogue: 2,{T(a)},{T(b)},C,,0,0,0,,{{\\pos({W // 2},{y}){fx}\\1a&HFF&\\3c&H000000&\\3a&H90&"
                  f"\\bord12\\blur14\\shad0\\fad(220,120)}}{esc(big).replace(chr(10), '\\N')}")
        ev.append(f"Dialogue: 3,{T(a)},{T(b)},C,,0,0,0,,{{\\pos({W // 2},{y}){fx}\\bord0\\shad3\\4a&H60&"
                  f"\\fad(0,120)}}{txt}")

    # legenda corrida: palavras aparecem conforme sao faladas; so palavra-chave colorida
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


def write_ass_v7(path, words, total, split_windows, hl):
    """Legenda v7: toda palavra falada aparece (CAIXA ALTA, condensada, reta, palavra a palavra).
    hl = indices de palavras destacadas -> bloco proprio, amarelo, maior, com pop curto."""
    head = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: C,{CAP7_FONT},{CAP7_FS},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
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
                or (i not in hl and (len(cur) >= CHUNK7_WORDS or len(txt) + 1 + len(words[nxt]["w"]) > CHUNK7_CHARS
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
        fs = CAP7_FS
        if is_hl:
            chars = len(" ".join(toks))
            if chars > 14 and len(toks) > 1:            # quebra em 2 linhas equilibradas
                best = min(range(1, len(toks)), key=lambda c: abs(len(" ".join(toks[:c])) - len(" ".join(toks[c:]))))
                lines = [list(range(best)), list(range(best, len(toks)))]
            longest = max(len(" ".join(toks[k] for k in l)) for l in lines)
            fs = int(min(CAP7_FS * HL7_SCALE, 640 / (CAP7_CHARW * longest)))
        fill, halo = [], []
        for li, line in enumerate(lines):
            for j, k in enumerate(line):
                t = max(0, int((words[ch[k]]["s"] - s0) * 1000))
                tok = esc(toks[k])
                sep = " " if j < len(line) - 1 else ("\\N" if li < len(lines) - 1 else "")
                fill.append(f"{{\\alpha&HFF&\\t({t},{t + 90},\\alpha&H00&)}}{tok}{sep}")
                halo.append(f"{{\\3a&HFF&\\t({t},{t + 90},\\3a&H70&)}}{tok}{sep}")
        col = HL7_COLOR if is_hl else "&H00FFFFFF&"
        pop = "\\fscx110\\fscy110\\t(0,120,\\fscx100\\fscy100)" if is_hl else ""
        base = f"\\an5\\pos({W // 2},{y})\\fs{fs}{pop}\\fad(0,80)"
        ev.append(f"Dialogue: 1,{T(s0)},{T(end)},C,,0,0,0,,{{{base}\\1a&HFF&\\bord14\\blur16\\3c&H000000&}}"
                  + "".join(halo))
        ev.append(f"Dialogue: 2,{T(s0)},{T(end)},C,,0,0,0,,{{{base}\\1c{col}\\bord0\\shad0}}" + "".join(fill))
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(head + ev) + "\n")


# ---------------- legenda v8 ----------------
_font8 = {}


def tw8(file, text, fs):
    """largura do texto no libass (Pillow calibrado)."""
    from PIL import ImageFont
    if file not in _font8:
        _font8[file] = ImageFont.truetype(os.path.join(LIB, "fontes", file), 100)
    return _font8[file].getlength(text) * fs / 100 * RATIO8[file]


def bgr8(hexrgb):
    return f"&H00{hexrgb[4:6]}{hexrgb[2:4]}{hexrgb[0:2]}&".upper()


def write_ass_v8(path, words, total, split_windows, imps, hls):
    """Legenda v8 (SKILL.md "Padrao v8 aprovado"). imps = [(indices, cfg IMPACT8)], hls = [(indices, estilo)].
    Uma legenda por vez no centro; destaque pequeno = comeco da frase na legenda comum + parte forte grande embaixo;
    impacto = tela cheia palavra a palavra. Retorna (janelas de blur, sons [(t, cat, ganho, prioridade)])."""
    T = ass_time
    fs = CAP8_FS
    halo = "\\1a&HFF&\\bord8\\blur10\\3c&H000000&\\3a&H80&\\shad0"
    in_split = lambda t: any(a - 1e-3 <= t < b - 1e-3 for a, b in split_windows)    # tolerancia: fim do hook = 7.69 vs 7.6899
    used, units = set(), []
    for idx, cfg in imps:
        units.append({"kind": "imp", "idx": idx, "lead": [], "cfg": cfg})
        used |= set(idx)
    for idx, est in hls:
        if used & set(idx):
            continue
        lead, k = [], idx[0] - 1               # comeco da mesma frase (ate 4 palavras; para em pontuacao)
        while (k >= 0 and k not in used and words[k]["clip"] == words[idx[0]]["clip"] and len(lead) < 5
               and not re.search(r"[.!?,]$", words[k]["w"]) and words[k + 1]["s"] - words[k]["e"] <= 0.35):
            lead.insert(0, k)
            k -= 1
        if len(lead) > 4:                      # frase longa: so as ultimas palavras (a partir de "and/when..." se houver)
            lead = lead[-3:]
            k = next((j for j in range(1, len(lead) - 1) if norm(words[lead[j]]["w"]) in FW8), 0)
            lead = lead[k:]
        units.append({"kind": est, "idx": idx, "lead": lead})
        used |= set(idx) | set(lead)
    def split_sense(seg):
        """frase longa -> partes por unidade de sentido: corta em virgula, nunca depois de palavra de ligacao
        nem entre numero e unidade; partes equilibradas, ate ~40 caracteres (2 linhas)."""
        txt = " ".join(words[k]["w"] for k in seg)
        if (len(txt) <= 40 and len(seg) <= 8) or len(seg) < 2:
            return [seg]
        toks = [words[k]["w"] for k in seg]

        def cost(c):
            a, b = " ".join(toks[:c]), " ".join(toks[c:])
            p = abs(len(a) - len(b)) / 10
            p += 4 if norm(toks[c - 1]) in FW8 else 0
            p += 5 if re.search(r"\d", toks[c - 1]) else 0
            p -= 3 if toks[c - 1].endswith(",") else 0
            return p
        c = min(range(1, len(seg)), key=cost)
        return split_sense(seg[:c]) + split_sense(seg[c:])

    cur = []                                   # legenda comum: frase inteira, ate 2 linhas
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
        else:                                   # destaque segura na tela; a proxima legenda espera (atraso <= 0.9s)
            hold = 1.1 if u["kind"] == "imp" else 1.4
            ref = words[last]["s"] if u["kind"] == "imp" else words[u["idx"][0]]["s"]
            end = max(words[last]["e"] + 0.35, ref + hold)
            if nxt:     # so segura sobre conectivo fraco ("and…"); senao a legenda seguinte atrasa no maximo 0.25s
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
            yel = {k + 1 for k in num if k + 1 < len(toks) and norm(toks[k + 1]) in UNITS8}
            wid = lambda a, b: sum(tw8(CAP8_FILE, toks[k], fs) * (1.8 if k in num else 1) for k in range(a, b)) \
                + tw8(CAP8_FILE, " ", fs) * (b - a - 1)
            lines = [(0, len(toks))]
            if wid(0, len(toks)) > 600 and len(toks) > 1:
                c = min(range(1, len(toks)), key=lambda c: (0 if toks[c - 1].endswith(",") else 1,
                                                             abs(wid(0, c) - wid(c, len(toks)))))
                lines = [(0, c), (c, len(toks))]

            def fmt(k, hl):
                t = esc(toks[k])
                if k in num:
                    return f"{{\\fs{int(fs * 1.8)}{'' if hl else chr(92) + '1c' + bgr8(COR8['Y'])}}}{t}{{\\fs{fs}\\1c&H00FFFFFF&}}"
                if k in yel and not hl:
                    return f"{{\\1c{bgr8(COR8['Y'])}}}{t}{{\\1c&H00FFFFFF&}}"
                return t
            for L, extra, hl in ((0, halo, True), (1, "", False)):
                tx = "\\N".join(" ".join(fmt(k, hl) for k in range(a, b)) for a, b in lines)
                ev.append(f"Dialogue: {L},{T(s)},{T(e)},S,,0,0,0,,{{\\an5\\pos({W // 2},{Y8}){extra}\\fad(120,90)}}{tx}")
            if num:
                sfx.append((words[idx[num[0]]]["s"], "pop02", -18, 1))
        elif u["kind"] in ("hl", "lock"):
            lead = " ".join(words[i]["w"] for i in u["lead"])
            big = re.sub(r"[.,;:]+$", "", " ".join(words[i]["w"] for i in idx)).upper()
            if u["kind"] == "lock":                  # lockup: Montserrat Bold caixa alta
                bl, bfs = [big], 96
                bh = bfs * 1.0
            else:                                    # amarelo grande da v7 (League Gothic), 2 linhas se longo
                toks = big.split()
                bl = [big]
                if len(big) > 14 and len(toks) > 1:
                    c = min(range(1, len(toks)), key=lambda c: abs(len(" ".join(toks[:c])) - len(" ".join(toks[c:]))))
                    bl = [" ".join(toks[:c]), " ".join(toks[c:])]
                bfs = int(min(170, 640 / max(tw8(LG8_FILE, l, 100) for l in bl) * 100))
                bh = bfs * 0.86 * (len(bl) - 1) + bfs * 0.75
            # bloco compacto e centrado no quadro; pode atravessar a costura do split (Felipe: "nao precisa
            # considerar a divisoria tao estritamente" — palavras longe uma da outra ficou ruim)
            lh = 58 if lead else 0
            top = Y8 + globals().get("HL_DY", 0) - (lh + bh) / 2   # HL_DY (job_config): desce o destaque quando o rosto e grande (AD02)
            if lead:
                for L, extra in ((0, halo), (1, "")):
                    ev.append(f"Dialogue: {L},{T(s)},{T(e)},S,,0,0,0,,{{\\an5\\pos({W // 2},{top + lh / 2:.0f}){extra}\\fad(120,90)}}{esc(lead)}")
            t_big = max(s, words[idx[0]]["s"])
            big_halo = halo.replace("bord8", "bord12").replace("blur10", "blur16")
            pitch = bfs * 0.86            # cada linha em evento proprio: \N usa a entrelinha alta da League Gothic
            for li, l in enumerate(bl):
                yl = top + lh + bfs * 0.375 + li * pitch
                if u["kind"] == "lock":
                    sty, fx = "S", f"\\b1\\fs{bfs}\\move({W // 2},{yl + 12:.0f},{W // 2},{yl:.0f},0,160)"
                else:
                    sty, fx = "L", (f"\\fs{bfs}\\pos({W // 2},{yl:.0f})\\fscx80\\fscy80\\t(0,90,\\fscx106\\fscy106)"
                                    f"\\t(90,170,\\fscx100\\fscy100)")
                for L, extra in ((2, big_halo), (3, f"\\1c{bgr8(COR8['Y'])}\\shad3")):
                    ev.append(f"Dialogue: {L},{T(t_big)},{T(e)},{sty},,0,0,0,,{{\\an5{fx}{extra}\\fad(80,90)}}{esc(l)}")
            sfx.append((t_big, "pop02" if re.search(r"\d", big) else "click05", -18, 1))
        else:                                        # impacto de tela cheia
            cfg = u["cfg"]
            up = [re.sub(r",$", "", words[i]["w"]).upper() for i in idx]
            keys = [norm(words[i]["w"]) for i in idx]
            cor, grande = cfg.get("cor", {}), cfg.get("grande", set())
            lines, k0 = [], 0
            for c in cfg.get("linhas", [len(up)]):
                lines.append(list(range(k0, min(k0 + c, len(up)))))
                k0 += c
            lfs = []
            for line in lines:
                fit = 650 / tw8(LG8_FILE, " ".join(up[k] for k in line), 100) * 100
                forte = any(keys[k] in cor or keys[k] in grande for k in line)
                so_num = len(line) == 1 and re.search(r"\d", up[line[0]])     # "$5" sozinho na linha: gigante
                lfs.append(min(fit, 340 if (forte and so_num) else 250 if forte else 165))
            sc = min(1.0, 640 / (0.80 * sum(lfs)))
            lfs = [int(f * sc) for f in lfs]
            hs = [0.80 * f for f in lfs]
            ytop = 505 - sum(hs) / 2
            for li, line in enumerate(lines):
                f_ = lfs[li]
                sp = tw8(LG8_FILE, " ", f_)
                x = W / 2 - tw8(LG8_FILE, " ".join(up[k] for k in line), f_) / 2
                for k in line:
                    wk = tw8(LG8_FILE, up[k], f_)
                    cx, cy = x + wk / 2, ytop + sum(hs[:li]) + hs[li] / 2
                    x += wk + sp
                    t0 = max(s, words[idx[k]]["s"])
                    col = bgr8(COR8[cor.get(keys[k], "W")])
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
        f"Style: S,{CAP8_FAM},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,0,2.5,5,0,0,0,1",
        f"Style: L,{LG8_FAM},120,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1",
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
    splits = [(starts[0], hook_end)] if starts else []   # hook sem b-roll (HOOK_SPLITS vazio) = sem painel dividido
    for key, clip, ph in BODY_BROLL + PILLS_BODY.get(letter, []):
        try:
            a, b, _ = phrase_window(words, clip, ph, total)
        except ValueError as e:
            print("AVISO:", e)
            continue
        # BODY_SPLIT (AD02 carro): b-roll do body no painel de baixo, rosto em cima, em vez de tela cheia
        ov.append({"key": key, "a": a, "b": max(b, a + 1.8), "mode": "split" if globals().get("BODY_SPLIT") else "full"})

    # lip-sync quebrado -> cobertura (prioridade sobre b-roll normal)
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
        cov = {**COVER, **globals().get("COVER8", {})} if is_v8() else COVER
        keys = cov.get(clip, ["honey"])
        if keys is None:                       # v8: coberto por impacto com blur (IMPACT8), sem b-roll
            continue
        parts = keys if b - a > 3.0 and len(keys) > 1 else keys[:1]
        step = (b - a) / len(parts)
        for i, k in enumerate(parts):
            ov.append({"key": k, "a": a + i * step, "b": a + (i + 1) * step, "mode": "cover"})

    # resolve sobreposicao: cover vence
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

    # nenhum bloco sem rosto > 7s: encurta o ultimo b-roll normal do bloco
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
    if globals().get("BODY_SPLIT"):    # painel de rosto em cima so onde ha b-roll embaixo (depois de cortes/coberturas)
        splits += [(o["a"], o["b"]) for o in overlays if o["mode"] == "split" and o["a"] >= hook_end - 1e-3]

    # nenhum arquivo de remedio repetido no mesmo video
    pill_files = [BROLL[o["key"]][0] for o in overlays if o["key"].startswith("pills")]
    assert len(pill_files) == len(set(pill_files)), f"remedio repetido em {letter}: {pill_files}"

    # relatorio lip-sync antes (v3) / depois (v4)
    iv = [(ta, tb) for _, ta, tb in broken]
    v3 = []
    p3 = os.path.join(V3PLAN, f"plano_{letter}.json")
    if os.path.exists(p3):
        with open(p3, encoding="utf-8") as f:
            v3 = [{"a": o["de"], "b": o["ate"], "mode": o["modo"]} for o in json.load(f)["broll"]]
    before, after = coverage(iv, v3), coverage(iv, overlays)
    REPORT.append((letter, broken, before, after))

    # impactos v6: frase LITERAL palavra a palavra (kinetic.py), scrim opcional, icone opcional
    impacts, k_events, k_cov, scrims, icons, k_sfx = [], [], [], [], [], []
    hl7 = globals().get("HIGHLIGHT")
    clips_here = {w["clip"] for w in words}
    hl_idx = set()
    for clip, ph in (hl7 or []):
        if clip in clips_here:
            hl_idx.update(find_phrase(words, clip, ph))
    v6 = None if hl7 else globals().get("IMPACT6")
    if v6:
        found = []
        for it in v6:
            if not any(w["clip"] == it["clip"] for w in words):
                continue
            try:
                a, b, idx = phrase_window(words, it["clip"], it["phrase"], total)
            except ValueError as e:
                print("AVISO:", e)
                continue
            found.append((a, b, idx, it))
        found.sort(key=lambda x: x[0])
        for n_, (a, b, idx, it) in enumerate(found):
            nxt = found[n_ + 1][0] if n_ + 1 < len(found) else total
            last_t = words[idx[-1]]["s"]
            end = min(max(b + 0.35, last_t + it.get("hold", 1.1)), nxt - 0.05, total)   # ultima palavra fica >= hold
            toks = kinetic.tokens_from_words([words[i] for i in idx])
            times = [words[i]["s"] for i in idx]
            colors = {k: COLORS6[c] for k, t in enumerate(toks) for w_, c in it.get("accent", {}).items()
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
    elif not hl7:
        for clip, ph, lead, bigt, kind, color in IMPACT:
            if not any(w["clip"] == clip for w in words):
                continue
            try:
                a, b, idx = phrase_window(words, clip, ph, total)
            except ValueError as e:
                print("AVISO:", e)
                continue
            impacts.append((a, b, idx, lead, bigt, kind, color))
        impacts.sort(key=lambda x: x[0])
    cards = [(x[0], max(x[1], x[0] + 1.0)) for x in impacts if x[5] == "card"]

    os.makedirs(WORK, exist_ok=True)
    ass_name = f"legenda_{letter}.ass"
    first_split = next((o for o in overlays if o["mode"] == "split" and o["a"] < hook_end), None)   # flash so na entrada do split do hook
    blur8 = []
    if is_v8():
        imps = [(find_phrase(words, it["clip"], it["phrase"]), it) for it in IMPACT8 if it["clip"] in clips_here]
        sty8 = globals().get("HIGHLIGHT8_STYLE", {})
        hls = [(find_phrase(words, clip, ph), sty8.get((clip, ph), "hl")) for clip, ph in (hl7 or []) if clip in clips_here]
        blur8, cand = write_ass_v8(os.path.join(WORK, ass_name), words, total, splits, imps, hls)
        # impacto com b-roll atras (full, cover ou painel do split): sem blur/escurecimento, para ver o b-roll e o
        # avatar (Felipe, 15/10); blur so quando o fundo e so o avatar
        # (AD02: se o b-roll so cobre PARTE da janela, o blur continua no trecho que e so avatar — antes a janela inteira
        # perdia o blur e o texto ficava sobre o rosto nitido, ex. "REVERSE ALZHEIMER'S" nos oculos)
        nb = []
        for a, b in blur8:
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
        blur8 = nb
        # relatorio de lip-sync conta o blur do impacto como cobertura
        REPORT[-1] = (letter, broken, before, coverage(iv, overlays + [{"a": a, "b": b, "mode": "cover"} for a, b in blur8]))
        # sons v8: looming na abertura, flash na entrada do split, sons dos impactos (prioridade 0) e POP 02/CLICK 05 dos
        # destaques pequenos so se nao houver outro som a menos de 3s (SFX enxuto)
        ev = [(0.0, "looming", -15)]
        if first_split:
            ev.append((first_split["a"] - 0.03, "flash", -12))
        for t, cat, g, pri in sorted(cand, key=lambda x: (x[3], x[0])):
            if pri == 0 or all(abs(t - t2) > 3.0 for t2, _, _ in ev):
                ev.append((t, cat, g))
        # BROLL_SFX (job_config): whoosh/swipe suave na entrada do b-roll do body, alternando os sons do banco v8, so com
        # folga de outros sons (AD02 carro, Felipe 20/10: "senti falta dos efeitos sonoros")
        bs = globals().get("BROLL_SFX")
        if bs:
            k = 0
            for o in overlays:
                if o["a"] >= hook_end - 1e-3 and all(abs(o["a"] - t2) > bs["gap"] for t2, _, _ in ev):
                    ev.append((o["a"] - 0.12, bs["cats"][k % len(bs["cats"])], bs["db"]))
                    k += 1
    elif hl7:
        write_ass_v7(os.path.join(WORK, ass_name), words, total, splits, hl_idx)
        # SFX v7: looming na abertura, flash na entrada do split e nos trechos do SFX7, clock em tempo, cymbal antes do CTA
        ev = [(0.0, "looming", -17)]
        if first_split:
            ev.append((first_split["a"] - 0.03, "flash", -13))
        for clip, ph, cat, db in SFX7:
            if clip not in clips_here:
                continue
            t0 = words[find_phrase(words, clip, ph)[0]]["s"]
            ev.append((t0 - 0.03, cat, db))
            if ph.startswith("tap"):
                ev.append((t0 - 1.74, "cymbal", -16))
    else:
        write_ass(os.path.join(WORK, ass_name), words, total, splits, impacts, k_events, k_cov)
        # SFX enxuto: abertura, entrada do split, cartoes, 1-2 manchetes de dor no hook, CTA
        ev = [(0.0, "impact", -10), (0.0, "whoosh", -15)]
        if first_split:
            ev.append((first_split["a"], "whoosh", -17))
        for a, b in cards:
            ev.append((a - 0.05, "swoosh", -14))
        hook_pain = [x for x in impacts if x[2] and words[x[2][0]]["clip"] == hook and x[5] == "head" and x[6] == "R"]
        for x in hook_pain[:2]:
            ev.append((x[0], "pop", -17))
        for x in impacts:
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
    for ff in ([CAP8_FILE, LG8_FILE] if is_v8() else [CAP7_FILE] if hl7 else []):
        if not os.path.exists(os.path.join(fdir, ff)):
            shutil.copy(os.path.join(LIB, "fontes", ff), fdir)
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
        sl = ext_.get("slow", 1.0)      # slow (job_config): camera lenta; le so (dur / slow) da fonte, para nao sair da janela limpa
        cmd += ["-ss", f"{src:.3f}", "-t", f"{(o['b'] - o['a']) / sl + (0.5 if sl == 1.0 else 0.05):.3f}", "-i", asset_path(f_)]
    i_sfx = n + len(overlays)
    cmd += ["-i", sfx_path, "-i", grad]
    i_grad = i_sfx + 1
    scrim_png = os.path.join(ASSETS, "scrim.png")
    if not os.path.exists(scrim_png):
        Image_ = __import__("PIL.Image", fromlist=["Image"])
        Image_.new("RGBA", (W, H), (6, 6, 10, 150)).save(scrim_png)
    i_scr = i_grad + 1
    if scrims:                      # 1 entrada so; repetida no filtro (PNG em -loop 1 trava o ffmpeg)
        cmd += ["-i", scrim_png]
    i_ico = i_scr + (1 if scrims else 0)
    for mov, a, b, x, y in icons:
        cmd += ["-t", f"{b - a:.3f}", "-i", mov]

    fc = []
    for i in range(n):
        z = PUNCH if i % 2 else 1.0
        sw = int(round(W * z / 2) * 2)
        sh = int(round(sw * 736 / 400 / 2) * 2)
        chain = f"[{i}:v]{FIX},scale={sw}:{sh},crop={W}:{H}:(iw-{W})/2:(ih-{H})*0.35,fps={FPS},setsar=1"
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
    # SPLIT_TOP_Y (job_config): onde o painel de cima comeca no quadro do avatar; AD02 carro = 180 (rosto mais baixo:
    # em 24 a costura e a legenda tampavam boca e queixo)
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
        pre = f",crop={ext['precrop']}" if ext.get("precrop") else ""   # remove tarja preta da fonte
        slow = f",setpts={ext['slow']}*PTS" if ext.get("slow") else ""
        chain = (f"{FIX}{pre},scale={tw}:{tth}:force_original_aspect_ratio=increase,crop={W}:{th}:(iw-{W})/2:(ih-{th})*{anc}"
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
    if blur8:              # impacto v8: o proprio video com blur forte + escurecido so na janela (trim = barato)
        fc.append(f"[gr]split={len(blur8) + 1}[gq]" + "".join(f"[gc{k}]" for k in range(len(blur8))))
        lq = "gq"
        for k, (a, b) in enumerate(blur8):
            fc.append(f"[gc{k}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS,gblur=sigma=26,"
                      f"eq=brightness=-0.20:saturation=0.85,format=yuva420p,fade=t=in:st=0:d=0.15:alpha=1,"
                      f"fade=t=out:st={max(0, b - a - 0.15):.3f}:d=0.15:alpha=1,setpts=PTS+{a:.3f}/TB[gb{k}]")
            fc.append(f"[{lq}][gb{k}]overlay=0:0:eof_action=pass[gz{k}]")
            lq = f"gz{k}"
        fc.append(f"[{lq}]format=yuv420p[grb]")
    glab = "grb" if blur8 else "gr"
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
    out = os.path.join(OUT, f"{PREFIX}_CLONE_HOOK_{letter}{var}_720p_{'v8' if is_v8() else 'v7'}.mp4")
    limit = float(os.environ.get("V7_TEST", 0)) or total
    if os.environ.get("V7_TEST"):
        out = os.path.join(WORK, f"teste_{letter}.mp4")
    frm = ["-ss", os.environ["V7_FROM"]] if os.environ.get("V7_FROM") else []
    # filtro em arquivo: com muitos b-rolls (AD02 carro) a linha passa do limite do Windows (WinError 206)
    fc_name = f"filtro_{letter}.txt"
    with open(os.path.join(WORK, fc_name), "w", encoding="utf-8") as f:
        f.write(";\n".join(fc))
    cmd += ["-/filter_complex", fc_name, "-map", "[vout]", "-map", "[aout]"] + frm + ["-t", f"{limit:.3f}",
            "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", out]
    run(cmd, cwd=WORK)

    plan = {"versao": letter, "duracao": round(total, 2),
            "broll": [{"b": o["key"], "arquivo": BROLL[o["key"]][0], "de": round(o["a"], 2), "ate": round(o["b"], 2),
                       "modo": o["mode"]} for o in overlays],
            "impactos": len(k_cov) or len(impacts), "scrims": len(scrims), "icones": len(icons),
            "sfx": [{"t": u[0], "cat": u[1], "arquivo": u[2], "db": u[3]} for u in used]}
    with open(os.path.join(WORK, f"plano_{letter}.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f, indent=2, ensure_ascii=False)
    print(f"{letter}: {total:.1f}s | b-rolls {len(overlays)} | impactos {len(k_cov) or len(impacts)} (scrims {len(scrims)}, icones {len(icons)}) | sfx {len(used)}")


def write_report():
    lines = [f"RELATORIO LIP-SYNC — {PREFIX}", "",
             "Deteccao: lipsync.py — rastreio da cabeca por template + movimento da boca alinhada a 15fps,",
             "fala ativa = palavras do Whisper; quebrado = fala com boca parada (< 38% da mediana) por > 0.4s.", ""]
    for letter, broken, before, after in REPORT:
        lines.append(f"VERSAO {letter}")
        for (clip, a, b), x, y in zip(broken, before, after):
            m = lambda t: f"{int(t // 60)}:{t % 60:05.2f}"
            lines.append(f"  {clip:7s} {m(a)} - {m(b)}  ({b - a:.2f}s)   antes: {x * 100:5.1f}% coberto   "
                         f"depois: {y * 100:5.1f}% coberto")
        lines.append("")
    partial = os.environ.get("V7_TEST") or len(REPORT) < len(VERSIONS)   # teste/parcial nao sobrescreve o oficial
    name = f"lipsync_report{'_' + VARIANT if VARIANT else ''}.txt"
    with open(os.path.join(WORK if partial else OUT, name), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("uso: python motor/montar.py jobs/<job> [A B C]")
    load_job(sys.argv[1])
    bank = SfxBank(seed=7)
    for v in (sys.argv[2:] or VERSIONS):
        build(v.upper(), bank)
    write_report()

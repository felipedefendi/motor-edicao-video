r"""Montagem do Passo 9: substitui SO as janelas declaradas, mantendo o resto do video, o audio e a
duracao exatamente como no original.

Uso:  py -3.12 motor\montar_trechos.py jobs\<job> [--saida nome.mp4] [--sem-perdas]

Le jobs/<job>/docs/janelas.json:
[
  {"trecho": 1, "inicio": 12.40, "fim": 15.00, "clipe": "work/clipes/t01.mp4",
   "metodo": "clipe novo (Grok)", "fade": 0.08, "inicio_clipe": 0.0}
]
- `inicio`/`fim`  : segundos no ORIGINAL (a janela que sai do ar)
- `clipe`         : o que entra no lugar, caminho relativo ao job
- `inicio_clipe`  : de que ponto do clipe comecar (default 0)
- `fade`          : segundos de crossfade em cada ponta para a emenda nao saltar (default 0.08; 0 desliga)

Estrategia: um unico passe de ffmpeg sobrepondo cada clipe no original com limites inteiros de quadros em `enable`.
Nada e cortado nem concatenado, por isso a grade de quadros do original e preservada quadro a quadro
e o audio pode ser copiado sem reencode (`-c:a copy`).

Depois de renderizar, rodar SEMPRE motor\auditar_render.py — sem laudo nao ha entrega.
"""
import glob
import json
import os
import subprocess
import sys

CRF = "0" if "--sem-perdas" in sys.argv else "16"          # trecho de VSL longa: perda visivel aqui aparece como remendo
PRESET = "fast" if "--sem-perdas" in sys.argv else "slow"
SETP = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709"


def ffprobe(src):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,r_frame_rate,nb_frames", "-show_entries",
                          "format=duration", "-of", "json", src],
                         capture_output=True, text=True)
    if out.returncode:
        raise SystemExit(out.stderr[-2000:])
    j = json.loads(out.stdout)
    v = j["streams"][0]
    n, _, d = v["r_frame_rate"].partition("/")
    return int(v["width"]), int(v["height"]), float(n) / float(d or 1), float(j["format"]["duration"])


def main():
    job = sys.argv[1].rstrip("\\/")
    saida = sys.argv[sys.argv.index("--saida") + 1] if "--saida" in sys.argv else "render.mp4"
    src = sorted(glob.glob(os.path.join(job, "entrada", "*.mp4")))[0]
    # utf-8-sig: arquivo escrito pelo PowerShell vem com BOM
    janelas = json.load(open(os.path.join(job, "docs", "janelas.json"), encoding="utf-8-sig"))
    janelas = [j for j in janelas if j.get("clipe")]
    if not janelas:
        raise SystemExit("nenhuma janela com clipe em docs/janelas.json")

    W, H, FPS, DUR = ffprobe(src)
    ent = os.path.join(job, "entrega")
    hist = os.path.join(ent, "_historico")
    os.makedirs(hist, exist_ok=True)
    dst = os.path.join(ent, saida)
    if os.path.exists(dst):
        i = 1
        while os.path.exists(os.path.join(hist, f"{i:02d}_{saida}")):
            i += 1
        os.replace(dst, os.path.join(hist, f"{i:02d}_{saida}"))

    janelas.sort(key=lambda j: j["inicio"])
    fim_ant = -1.0
    for j in janelas:
        if j["inicio"] < fim_ant:
            raise SystemExit(f"janelas sobrepostas em {j['inicio']}s — separar antes de montar")
        if j["fim"] > DUR + 1e-3:
            raise SystemExit(f"janela {j} passa do fim do original ({DUR:.3f}s)")
        fim_ant = j["fim"]

    args = ["ffmpeg", "-v", "error", "-stats", "-y", "-filter_complex_threads", "1", "-threads", "2", "-i", src]
    for j in janelas:
        args += ["-threads", "2", "-i", os.path.join(job, j["clipe"])]

    fc, base = [], "base"
    fc.append(f"[0:v]{SETP},fps={FPS}[base]")
    for n, j in enumerate(janelas, start=1):
        a, b = float(j["inicio"]), float(j["fim"])
        primeiro, limite = round(a * FPS), round(b * FPS)
        a, b = primeiro / FPS, limite / FPS
        dsec = b - a
        off = float(j.get("inicio_clipe", 0.0))
        fade = float(j.get("fade", 0.08))
        lbl = f"c{n}"
        # clipe: recorta a duracao exata da janela, casa resolucao/fps e desloca para t=a
        v = (f"[{n}:v]{SETP},trim=start={off}:duration={dsec},setpts=PTS-STARTPTS,"
             f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,"
             f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,format=yuva420p")
        if fade > 0:
            v += (f",fade=t=in:st=0:d={fade}:alpha=1"
                  f",fade=t=out:st={max(dsec - fade, 0):.4f}:d={fade}:alpha=1")
        v += f",setpts=PTS+{a}/TB[{lbl}]"
        fc.append(v)
        out = f"v{n}"
        fc.append(f"[{base}][{lbl}]overlay=0:0:eof_action=pass:"
                  f"enable='gte(n,{primeiro})*lt(n,{limite})'[{out}]")
        base = out
    fc.append(f"[{base}]format=yuv420p[vout]")

    args += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "0:a?",
             "-c:v", "libx264", "-threads", "4", "-preset", PRESET, "-crf", CRF, "-pix_fmt", "yuv420p",
             "-r", f"{FPS}", "-c:a", "copy", "-movflags", "+faststart", dst]

    print(f"original {W}x{H} @ {FPS} fps, {DUR:.3f}s | {len(janelas)} janelas")
    p = subprocess.run(args)
    if p.returncode:
        raise SystemExit("render falhou")

    w2, h2, f2, d2 = ffprobe(dst)
    print(f"render: {w2}x{h2} @ {f2} fps, {d2:.3f}s -> {dst}")
    if (w2, h2) != (W, H) or abs(d2 - DUR) > 1.0 / FPS:
        print("AVISO: render divergiu do original. NAO entregar; investigar antes.")
    print("Agora: py -3.12 motor\\auditar_render.py " + job)


if __name__ == "__main__":
    main()

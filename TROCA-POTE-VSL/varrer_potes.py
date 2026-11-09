r"""Varredura do trecho de VSL: folhas de contato numeradas + indice de tempo, para EU olhar e marcar
onde o pote e o preco aparecem.

Uso:  py -3.12 motor\varrer_potes.py jobs\<job> [fps]

Gera em jobs/<job>/work/varredura/:
  folha_000.png, folha_001.png ...   tiles 6x4, 24 quadros por folha
  indice.json                        folha -> posicao no tile -> timestamp do quadro
E grava jobs/<job>/docs/contrato_tecnico.json com o que o render final tem que respeitar.

Nao decide nada: quem marca a aparicao do pote sou eu, olhando as folhas, e o Felipe completa.
Nao usa drawtext (sem fontconfig neste PC): a numeracao e pela posicao no tile, lida no indice.json.
"""
import json
import os
import subprocess
import sys

COLS, ROWS = 6, 4
PER_SHEET = COLS * ROWS
TILE_W = 240


def run(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise SystemExit(f"falhou: {' '.join(args[:3])}...\n{p.stderr[-2000:]}")
    return p.stdout


def contrato(src, out):
    v = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames,pix_fmt",
                        "-of", "json", src]))["streams"][0]
    a = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
                        "stream=codec_name,sample_rate,channels,bit_rate", "-of", "json", src]))
    f = json.loads(run(["ffprobe", "-v", "error", "-show_entries", "format=duration,size",
                        "-of", "json", src]))["format"]
    c = {"origem": os.path.abspath(src), "video": v,
         "audio": a["streams"][0] if a.get("streams") else None, "formato": f}
    c["vfr_suspeito"] = v.get("r_frame_rate") != v.get("avg_frame_rate")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(c, fh, indent=2, ensure_ascii=False)
    return c


def main():
    job = sys.argv[1].rstrip("\\/")
    fps = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    ent = os.path.join(job, "entrada")
    mp4 = [f for f in sorted(os.listdir(ent)) if f.lower().endswith((".mp4", ".mov", ".mkv"))]
    if not mp4:
        raise SystemExit(f"nenhum video em {ent}")
    src = os.path.join(ent, mp4[0])
    work = os.path.join(job, "work", "varredura")
    docs = os.path.join(job, "docs")
    os.makedirs(work, exist_ok=True)
    os.makedirs(docs, exist_ok=True)

    c = contrato(src, os.path.join(docs, "contrato_tecnico.json"))
    dur = float(c["formato"]["duration"])
    print(f"entrada: {mp4[0]}  {c['video']['width']}x{c['video']['height']}  "
          f"{c['video'].get('r_frame_rate')} fps  {dur:.2f}s")
    if c["vfr_suspeito"]:
        print("AVISO: r_frame_rate != avg_frame_rate -> pode ser VFR. Ver Passo 1 da SKILL.md.")
    if c["video"]["width"] > c["video"]["height"]:
        print("AVISO: video horizontal. Esta skill pressupoe 9:16 -> parar e perguntar ao Felipe.")

    sheets = int(dur * fps // PER_SHEET) + 1
    run(["ffmpeg", "-v", "error", "-y", "-i", src,
         "-vf", f"fps={fps},scale={TILE_W}:-2,tile={COLS}x{ROWS}:padding=4:color=0x202020",
         "-frames:v", str(sheets), "-start_number", "0",
         os.path.join(work, "folha_%03d.png")])

    indice, n = [], 0
    for s in range(sheets):
        nome = f"folha_{s:03d}.png"
        if not os.path.exists(os.path.join(work, nome)):
            break
        tiles = []
        for r in range(ROWS):
            for col in range(COLS):
                t = n / fps
                if t <= dur:
                    tiles.append({"pos": f"L{r + 1}C{col + 1}", "t": round(t, 3),
                                  "mmss": f"{int(t) // 60:02d}:{t % 60:06.3f}"})
                n += 1
        indice.append({"folha": nome, "quadros": tiles})
    with open(os.path.join(work, "indice.json"), "w", encoding="utf-8") as fh:
        json.dump({"fps_amostragem": fps, "colunas": COLS, "linhas": ROWS,
                   "duracao_s": dur, "folhas": indice}, fh, indent=2, ensure_ascii=False)
    print(f"{len(indice)} folhas em {work}")
    print("Proximo: olhar cada folha, marcar as aparicoes do pote/preco e montar a folha de trechos "
          "(Passo 4); depois o Felipe completa o que faltou.")


if __name__ == "__main__":
    main()

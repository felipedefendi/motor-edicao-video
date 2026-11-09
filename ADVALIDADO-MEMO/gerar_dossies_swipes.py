from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(r"G:\Meu Drive\ADVALIDADO-MEMO\Ads Swipe Memoria")


def stamp(seconds: float) -> str:
    minutes = int(seconds // 60)
    return f"{minutes:02d}:{seconds - minutes * 60:05.2f}"


def exact_slice(segments: list[dict], start: float, end: float) -> str:
    selected = [s["text"].strip() for s in segments if s["start"] >= start - 0.02 and s["end"] <= end + 0.02]
    return " ".join(selected).strip()


def exact_phrase(full_copy: str, requested: str) -> str:
    match = re.search(re.escape(requested), full_copy, flags=re.IGNORECASE)
    if not match:
        raise ValueError(f"Trecho de impacto não é literal: {requested!r}")
    return full_copy[match.start() : match.end()]


def bullet_lines(values: list[str]) -> str:
    return "\n".join(f"- {value}" for value in values) if values else "- Não identificado"


def scene_description(scene: dict, blocks: list[dict]) -> str:
    midpoint = (float(scene["inicio_s"]) + float(scene["fim_s"])) / 2
    for block in blocks:
        if float(block["inicio_s"]) <= midpoint < float(block["fim_s"]):
            return block["descricao"]
    return "Mudança visual detectada automaticamente; consultar o frame."


def generate(ad_dir: Path) -> None:
    config_path = ad_dir / "analise" / "config_dossie.json"
    if not config_path.exists():
        return
    config = json.loads(config_path.read_text(encoding="utf-8"))
    whisper = json.loads((ad_dir / "transcricao" / "whisper.json").read_text(encoding="utf-8"))
    metadata = json.loads((ad_dir / "analise" / "metadata.json").read_text(encoding="utf-8"))
    scenes = json.loads((ad_dir / "analise" / "cenas_auto.json").read_text(encoding="utf-8"))
    segments = whisper["segments"]
    full_copy = whisper["text"].strip()
    duration = float(metadata["duracao_segundos"])
    hook_end = float(config["hook_end_s"])
    cta_start = float(config["cta_start_s"])
    hook = exact_slice(segments, 0.0, hook_end)
    body = exact_slice(segments, hook_end, cta_start)
    cta = exact_slice(segments, cta_start, duration + 1.0)
    impacts = [exact_phrase(full_copy, phrase) for phrase in config.get("impactos_literais", [])]

    copy_doc = f"""# Copy estruturada — {config['id']} {config['nome']}

> Transcrição literal do Whisper `medium`. Nenhuma palavra foi reescrita, corrigida, resumida ou adicionada. Consulte `../transcricao/palavras.csv` para timestamps e confiança de cada palavra.

## HOOK — 00:00.00 a {stamp(hook_end)}

{hook}

## BODY — {stamp(hook_end)} a {stamp(cta_start)}

{body}

## CTA — {stamp(cta_start)} a {stamp(duration)}

{cta}

## Trechos de impacto literais

{bullet_lines([f'“{p}”' for p in impacts])}

## Copy integral — literal

{full_copy}
"""
    (ad_dir / "analise" / "COPY_ESTRUTURADA.md").write_text(copy_doc, encoding="utf-8")

    dossier = f"""# {config['id']} — {config['nome']}

## Identificação

- Família/variação: {config.get('familia', 'peça única')}
- Arquivo: `{metadata['arquivo_original']}`
- Duração: {stamp(duration)}
- Resolução: {metadata['resolucao']} · FPS: {metadata['fps']} · codec: {metadata['codec_video']}
- SHA-256: `{metadata['sha256']}`
- Cenas automáticas detectadas: {len(scenes)}
- Conceito curto: {config['conceito']}

## Estrutura narrativa

- Hook: 00:00.00–{stamp(hook_end)} — {config['hook_resumo']}
- Body: {stamp(hook_end)}–{stamp(cta_start)} — {config['body_resumo']}
- CTA: {stamp(cta_start)}–{stamp(duration)} — {config['cta_resumo']}

As falas literais completas estão em [COPY_ESTRUTURADA.md](COPY_ESTRUTURADA.md). A divisão não altera a copy.

## Leitura visual e edição

- Padrão de fundo/cenário: {config['fundo']}
- Avatar/apresentador: {config['avatar']}
- Hook visual: {config['hook_visual']}
- Corpo visual: {config['corpo_visual']}
- Legendas e tipografia: {config['legendas']}
- Cores: {config['cores']}
- Ritmo e cortes: {config['ritmo']}
- B-roll/provas visuais: {config['broll']}
- Transições/efeitos: {config['efeitos']}
- CTA visual: {config['cta_visual']}

## Trechos de impacto — fala literal

{bullet_lines([f'“{p}”' for p in impacts])}

## Padrão reutilizável observado

{bullet_lines(config['padrao_reutilizavel'])}

## Materiais para estudo

- `../frames/overview.jpg`: visão geral em 20 pontos do vídeo.
- `../frames/timeline_5s/`: frame a cada 5 segundos.
- `../frames_cenas/`: primeiro frame de cada mudança visual detectada.
- `cenas_auto.csv`: frame a frame por cena, com início, fim e duração.
- `paleta_amostrada.json`: cores dominantes da timeline.
- `../transcricao/segmentos.txt`: copy literal com timestamps.
- `../transcricao/palavras.csv`: copy palavra por palavra com confiança.
- `../transcricao/whisper.json`: saída integral do Whisper.

## Observações de confiabilidade

{bullet_lines(config.get('observacoes', ['A copy permanece bruta; conferir palavras de baixa confiança no CSV antes de reutilizar.']))}
"""
    (ad_dir / "analise" / "DOSSIÊ.md").write_text(dossier, encoding="utf-8")

    scene_rows = []
    blocks = config.get("blocos_visuais", [])
    for scene in scenes:
        frame_link = "../" + scene["frame"].replace("\\", "/")
        scene_rows.append(
            f"| {scene['cena']:03d} | {stamp(float(scene['inicio_s']))} | {stamp(float(scene['fim_s']))} | "
            f"{float(scene['duracao_s']):.2f}s | [{Path(scene['frame']).name}]({frame_link}) | "
            f"{scene_description(scene, blocks)} |"
        )
    scene_doc = f"""# Decupagem visual por cena — {config['id']} {config['nome']}

> Os limites foram detectados por mudança visual a 2 fps. Cada linha aponta para o primeiro frame da cena. A descrição identifica o bloco visual correspondente; confirme microcortes diretamente nos frames quando necessário.

| Cena | Início | Fim | Duração | Frame | Descrição visual |
|---:|---:|---:|---:|---|---|
{chr(10).join(scene_rows)}

## Blocos visuais principais

{bullet_lines([f"{stamp(float(b['inicio_s']))}–{stamp(float(b['fim_s']))}: {b['descricao']}" for b in blocks])}
"""
    (ad_dir / "analise" / "DECUPAGEM_CENAS.md").write_text(scene_doc, encoding="utf-8")

    uncertain = []
    for segment in segments:
        for word in segment.get("words", []):
            probability = float(word.get("probability", 0.0))
            if probability < 0.60:
                uncertain.append(
                    f"| {stamp(float(word['start']))} | {stamp(float(word['end']))} | "
                    f"`{word['word']}` | {probability:.3f} | {segment['text'].strip()} |"
                )
    uncertain_doc = f"""# Palavras de baixa confiança — {config['id']} {config['nome']}

> Lista automática de palavras com confiança Whisper abaixo de 0,60. A copy não foi corrigida; este arquivo indica onde uma pessoa deve conferir o áudio original.

| Início | Fim | Palavra literal | Confiança | Contexto literal do segmento |
|---:|---:|---|---:|---|
{chr(10).join(uncertain) if uncertain else '| — | — | — | — | Nenhuma palavra abaixo do limite. |'}
"""
    (ad_dir / "analise" / "PALAVRAS_BAIXA_CONFIANCA.md").write_text(uncertain_doc, encoding="utf-8")
    print(f"{ad_dir.name}: dossiê gerado")


def main() -> None:
    for config_path in sorted(ROOT.rglob("analise/config_dossie.json")):
        generate(config_path.parent.parent)


if __name__ == "__main__":
    main()

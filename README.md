# Motor de Edição de Vídeo

Conjunto de scripts em Python que montam e auditam vídeos a partir da voz real,
operados de ponta a ponta por agentes de IA (Claude Code, Codex e Custom GPT).
Cada trabalho é descrito num arquivo de configuração próprio, e o mesmo motor
serve a qualquer job.

## O que o motor faz

- **Linha do tempo pela voz**: transcrição com Whisper (PyTorch/CUDA) com
  timestamps por palavra; o nível de áudio corrige o atraso do Whisper ao
  marcar palavras, e os cortes e aproximações nascem dessa linha do tempo.
- **Legendas animadas** palavra a palavra em ASS, com medição real da fonte
  (Pillow calibrado contra o libass) e ensaio de legendas antes do render.
- **Montagem**: tela dividida, movimento de câmera em imagens paradas, mapa
  de sobreposições de texto e B-roll, banco de efeitos sonoros cortados no
  ataque do som, demos de estilo para comparação.
- **Render** com FFmpeg usando filtros compostos e junção sem perdas em
  paralelo.
- **Visão computacional** com OpenCV: detector de boca fora de sincronia,
  rastreamento de movimento (ORB/RANSAC), preenchimento de fundo, máscaras
  por cor, sombra e composição para trocar um objeto dentro do vídeo.
- **Auditoria do resultado** comparando quadros do original e do render por
  histograma.
- **Separação de voz e trilha** com Demucs e troca de falas com voz clonada
  (ElevenLabs via REST API) e revisão fonética em contexto.

## Estrutura

| Pasta | Conteúdo |
|---|---|
| `ADVALIDADO-MEMO/` | Montagem completa: transcrição, legendas cinéticas, lip-sync, B-roll, SFX, demos de estilo e análise de variações. |
| `TROCA-POTE-VSL/` | Edição de vídeos longos: cortes, substituição de objeto em cena, restauração de letreiros, troca de falas e auditoria do render. |

## Requisitos

- Python 3.12+
- FFmpeg e ffprobe no PATH
- `openai-whisper`, `torch` (CUDA opcional), `opencv-python`, `pillow`,
  `numpy`, `demucs`

Os scripts leem a configuração de cada job em arquivo próprio e gravam
relatórios de auditoria ao lado do render.

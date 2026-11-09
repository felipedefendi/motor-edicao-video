# Video Editing Engine

A set of Python scripts that assemble, repair and audit short and long videos from the real voice track,
designed to be operated end to end by AI agents (Claude Code, Codex and Custom GPT skills). Every job is
described by its own config file, so the same engine serves any project.

## What it does

- **Timeline from the voice**: Whisper transcription (PyTorch/CUDA) with word timestamps; the audio
  envelope corrects the transcriber's late word boundaries, and cuts never land on a spoken word.
- **Captions**: three styles (running caption with headline cards, condensed upper case with yellow
  highlights, centred caption with full-screen emphasis), all rendered as ASS with real font measurement
  (Pillow calibrated against libass).
- **Assembly**: split-screen panels, b-roll with zoom and anchor control, scrims, animated emoji icons,
  a sound-effect bank cut on the transient, FFmpeg rendering with complex filter graphs.
- **Computer vision**: broken lip-sync detector, camera tracking (ORB + RANSAC) to composite a replacement
  object, inpainting repair, HSV masks to carry on-screen text over to a new clip, histogram-based render audit.
- **Audio**: voice/bed separation with Demucs, speech replacement with RMS matching and bounded time-stretch.
- **Reference study**: frame extraction, scene cuts, dominant colours, dossiers and presenter catalogues
  from reference videos.

## Layout

| Folder | Scripts |
|---|---|
| `assembly/` | `assemble.py` (main engine), `kinetic.py` (word-by-word typography), `lipsync.py`, `sfx_bank.py`, `caption_preview.py`, `overlay_map.py`, `demos/` (style sheets, style combos, SFX audition) |
| `longform/` | `scan_frames.py`, `scene_cuts.py`, `cutout_object.py`, `composite_object.py`, `restore_text.py`, `replace_speech.py`, `replace_windows.py`, `assemble_lossless.py`, `scan_onscreen_text.py`, `audit_render.py` |
| `analysis/` | `transcribe.py`, `extract_frames.py`, `build_dossier.py`, `find_shared_copy.py`, `extract_presenters.py`, `download_contact_sheet.ps1` |

## Job layout (assembly)

```
jobs/<job>/
  job_config.py          clips, b-roll per phrase, highlights, emphasis, lip-sync coverage
  avatar/<clip>.mp4      presenter takes
  avatar/transcripts/    Whisper JSON per clip
  work/<style>/          captions, filter graphs, plans and test renders
  output/                final renders and the lip-sync report
library/
  broll/  sfx/bank/  assets/  fonts/
```

## Job layout (long form)

```
jobs/<job>/
  input/original.mp4
  docs/windows.json      replaced windows: start, end, clip, fade
  docs/composite.json    object composite recipe per window
  docs/texts.json        on-screen text restoration per window
  docs/speech_swaps.json speech replacement recipe
  work/                  scans, cuts, clips, previews, suspects
  output/                renders (+ _history)
```

## Requirements

- Python 3.12+, FFmpeg and ffprobe on the PATH
- `pip install -r requirements.txt` (`openai-whisper`, `torch`, `opencv-python`, `pillow`, `numpy`,
  `demucs`, `soundfile`, `easyocr`)
- Fonts referenced by the caption styles in `library/fonts/`

Every render is followed by an audit: the engine reduces the video to a short list of frames and numbers
for a person to check before delivery.

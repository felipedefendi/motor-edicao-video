from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path


ROOT = Path(r"G:\Meu Drive\ADVALIDADO-MEMO\Ads Swipe Memoria")


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9$%']+", text.lower())


def main() -> None:
    copies: dict[str, tuple[list[str], str]] = {}
    for path in sorted(ROOT.rglob("transcricao/whisper.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        ad_dir = path.parent.parent
        config = ad_dir / "analise" / "config_dossie.json"
        ad_id = json.loads(config.read_text(encoding="utf-8"))["id"] if config.exists() else ad_dir.name
        copies[ad_id] = (tokens(data["text"]), data["text"].strip())

    rows = []
    for left, right in combinations(copies, 2):
        left_tokens, _ = copies[left]
        right_tokens, _ = copies[right]
        matcher = SequenceMatcher(None, left_tokens, right_tokens, autojunk=False)
        block = max(matcher.get_matching_blocks(), key=lambda item: item.size)
        if block.size >= 45:
            excerpt = " ".join(left_tokens[block.a : block.a + min(block.size, 35)])
            rows.append((block.size, left, right, block.a, block.b, excerpt))

    rows.sort(reverse=True)
    output = [
        "# Candidatos a variações por copy compartilhada",
        "",
        "> Detecção automática por maior sequência literal de palavras em comum. 45 palavras equivalem aproximadamente a 18 segundos; combinações próximas ou acima de 75 palavras merecem verificação visual para a regra de 30 segundos.",
        "",
        "| Palavras consecutivas | A | B | Posição A | Posição B | Início do trecho literal comum |",
        "|---:|---|---|---:|---:|---|",
    ]
    output.extend(
        f"| {size} | {left} | {right} | {pos_left} | {pos_right} | {excerpt}… |"
        for size, left, right, pos_left, pos_right, excerpt in rows
    )
    (ROOT / "VARIACOES_CANDIDATAS.md").write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"{len(copies)} copies comparadas; {len(rows)} pares candidatos")


if __name__ == "__main__":
    main()

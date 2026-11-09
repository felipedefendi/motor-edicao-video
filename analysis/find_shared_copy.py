"""Finds pairs of references that share a long literal run of words (candidate variations of one script).

Usage: python analysis/find_shared_copy.py <root> [--min-words 45]
Writes <root>/SHARED_COPY_CANDIDATES.md.
"""
from __future__ import annotations

import argparse
import json
import re
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9$%']+", text.lower())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root")
    parser.add_argument("--min-words", type=int, default=45)
    args = parser.parse_args()
    root = Path(args.root)

    texts: dict[str, tuple[list[str], str]] = {}
    for path in sorted(root.rglob("transcript/whisper.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        ref_dir = path.parent.parent
        config = ref_dir / "analysis" / "dossier_config.json"
        ref_id = json.loads(config.read_text(encoding="utf-8"))["id"] if config.exists() else ref_dir.name
        texts[ref_id] = (tokens(data["text"]), data["text"].strip())

    rows = []
    for left, right in combinations(texts, 2):
        left_tokens, _ = texts[left]
        right_tokens, _ = texts[right]
        matcher = SequenceMatcher(None, left_tokens, right_tokens, autojunk=False)
        block = max(matcher.get_matching_blocks(), key=lambda item: item.size)
        if block.size >= args.min_words:
            excerpt = " ".join(left_tokens[block.a: block.a + min(block.size, 35)])
            rows.append((block.size, left, right, block.a, block.b, excerpt))

    rows.sort(reverse=True)
    output = [
        "# Candidate variations by shared copy",
        "",
        f"> Automatic detection by the longest literal run of words in common. {args.min_words} words is roughly "
        "18 seconds of speech; pairs near or above 75 words deserve a visual check.",
        "",
        "| Consecutive words | A | B | Position A | Position B | Start of the shared run |",
        "|---:|---|---|---:|---:|---|",
    ]
    output.extend(
        f"| {size} | {left} | {right} | {pos_left} | {pos_right} | {excerpt}… |"
        for size, left, right, pos_left, pos_right, excerpt in rows
    )
    (root / "SHARED_COPY_CANDIDATES.md").write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"{len(texts)} texts compared; {len(rows)} candidate pairs")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build server/coach/data/openings.json from lichess-org/chess-openings TSV files."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import chess

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "server" / "coach" / "data"
OUTPUT = DATA_DIR / "openings.json"


def pgn_to_uci(pgn: str) -> list[str] | None:
    board = chess.Board()
    cleaned = re.sub(r"\d+\.+", " ", pgn)
    tokens = cleaned.split()

    moves: list[str] = []

    for token in tokens:
        if token in {"...", "..."}:
            continue

        try:
            move = board.parse_san(token)
        except ValueError:
            return None

        if move not in board.legal_moves:
            return None

        moves.append(move.uci())
        board.push(move)

    return moves


def split_name(full_name: str) -> tuple[str, str]:
    if ": " in full_name:
        base, variation = full_name.split(": ", 1)
        return base.strip(), variation.strip()

    return full_name.strip(), ""


def main() -> int:
    entries: list[dict[str, object]] = []
    seen: set[tuple[str, ...]] = set()

    for tsv_path in sorted(DATA_DIR.glob("*.tsv")):
        for line in tsv_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()

            if not line or line.startswith("eco\t"):
                continue

            parts = line.split("\t", 2)

            if len(parts) < 3:
                continue

            eco = parts[0].strip()
            name = parts[1].strip()
            pgn = parts[2].strip()
            uci_moves = pgn_to_uci(pgn)

            if not uci_moves:
                continue

            key = tuple(uci_moves)

            if key in seen:
                continue

            seen.add(key)

            base_name, variation = split_name(name)

            entries.append(
                {
                    "eco": eco,
                    "name": base_name,
                    "variation": variation,
                    "uci": uci_moves,
                }
            )

    OUTPUT.write_text(
        json.dumps(entries, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )

    print(f"Wrote {len(entries)} openings to {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Decode the indices used at the $_BJJQ call site."""
from __future__ import annotations

import pathlib

TASK = pathlib.Path(__file__).resolve().parent


def main() -> int:
    table: dict[int, str] = {}
    for line in (TASK / "cache" / "click_strings.tsv").read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit():
            table[int(parts[0])] = parts[1]
    for i in (824, 469, 785, 862, 748, 453, 830, 429, 587, 419, 874, 817, 696, 885, 444, 39, 653, 722, 729, 236, 732, 172, 750, 751, 774, 214):
        print(f"  {i} = {table.get(i, '?')!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

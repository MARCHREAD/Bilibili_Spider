"""Decode the string-table indices used around the click-tracker plumbing and
dump the tracker class definition + the $_CCAF grid builder in full.
"""
from __future__ import annotations

import pathlib
import re
import sys

TASK = pathlib.Path(__file__).resolve().parent
ASSET = TASK / "cache" / "click.patched-widget.js"
STRINGS = TASK / "cache" / "click_strings.tsv"
TEXT = ASSET.read_text(encoding="utf-8", errors="replace")

IDX = [802, 175, 186, 881, 888, 822, 469, 862, 874, 568, 39, 700, 444, 366,
       437, 447, 425, 66, 593, 824, 821, 497, 621, 112, 827, 885, 815, 419,
       440, 830, 748, 899, 804, 773, 739, 771, 653, 455, 587, 677, 453]


def load_strings() -> dict[int, str]:
    out: dict[int, str] = {}
    for line in STRINGS.read_text(encoding="utf-8", errors="replace").splitlines():
        p = line.split("\t")
        if len(p) < 2:
            continue
        try:
            out[int(p[0])] = p[-1]
        except ValueError:
            pass
    return out


def main() -> int:
    s = load_strings()
    print("=== decoded indices ===")
    for i in IDX:
        print(f"  {i:4d} -> {s.get(i)!r}")

    print("\n=== escaped $_FAA definition contexts ===")
    esc = "\\u0024\\u005f\\u0046\\u0041\\u0041"
    for m in re.finditer(re.escape(esc), TEXT):
        k = m.start()
        print(f"\n--- @{k} ---")
        print(TEXT[max(0, k - 120):k + 1500])

    print("\n=== $_CCAF grid-builder body (from its key) ===")
    key = "\\u0024\\u005f\\u0043\\u0043\\u0041\\u0046"
    j = TEXT.find(key)
    print(f"key at {j}")
    print(TEXT[j:j + 2600] if j >= 0 else "(not found)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

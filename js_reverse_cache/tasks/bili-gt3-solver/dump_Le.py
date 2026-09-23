"""Dump class Le (the word/phrase click tracker) methods and decode the extra
string-table indices used by $_CBCK.
"""
from __future__ import annotations

import pathlib
import re
import sys

TASK = pathlib.Path(__file__).resolve().parent
TEXT = (TASK / "cache" / "click.patched-widget.js").read_text(
    encoding="utf-8", errors="replace")
STRINGS = TASK / "cache" / "click_strings.tsv"

IDX = [551, 805, 656, 736, 797, 818, 848, 882, 890, 43, 434, 472, 468, 461,
       431, 449, 509, 567, 711, 833, 843, 867, 880, 808, 807, 849, 59, 37,
       703, 747, 798, 293, 298, 839, 893, 656, 888, 824, 175, 186, 366, 66,
       593, 802, 469, 461, 468]


def load_strings():
    out = {}
    for line in STRINGS.read_text(encoding="utf-8", errors="replace").splitlines():
        p = line.split("\t")
        if len(p) >= 2:
            try:
                out[int(p[0])] = p[-1]
            except ValueError:
                pass
    return out


def main() -> int:
    st = load_strings()
    print("=== decoded ===")
    for i in sorted(set(IDX)):
        print(f"  {i:4d} -> {st.get(i)!r}")

    for pat in ("Le[$_", "function Le(", "Me[$_", "ie[$_"):
        print(f"\n########## {pat} ##########")
        for m in re.finditer(re.escape(pat), TEXT):
            k = m.start()
            print(f"--- @{k} ---")
            print(TEXT[k:k + 2000])
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

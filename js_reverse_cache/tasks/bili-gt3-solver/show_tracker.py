"""Print the regions of cache/click.patched-widget.js where the click tracker
($ _CBIT, string idx 824) is constructed, and locate the tracker class whose
$ _FAA() serialises it (escaped form \\u0024\\u005f\\u0046\\u0041\\u0041).
"""
from __future__ import annotations

import pathlib
import re
import sys

TASK = pathlib.Path(__file__).resolve().parent
ASSET = TASK / "cache" / "click.patched-widget.js"
TEXT = ASSET.read_text(encoding="utf-8", errors="replace")

REGIONS = [
    ("site A (g[...824]=f)", 191200, 192000),
    ("site B (o[...824]=a)", 193100, 193900),
    ("submit call site", 203900, 205200),
]

ESC = {
    "$_FAA": "\\u0024\\u005f\\u0046\\u0041\\u0041",
    "$_CBIT": "\\u0024\\u005f\\u0043\\u0042\\u0049\\u0054",
    "$_CBDo": "\\u0024\\u005f\\u0043\\u0042\\u0044\\u006f",
    "$_CBDL": "\\u0024\\u005f\\u0043\\u0042\\u0044\\u004c",
    "$_BJJQ": "\\u0024\\u005f\\u0042\\u004a\\u004a\\u0051",
}


def main() -> int:
    for label, lo, hi in REGIONS:
        print(f"\n########## {label} [{lo}:{hi}] ##########")
        print(TEXT[lo:hi])
    for name, esc in ESC.items():
        hits = [m.start() for m in re.finditer(re.escape(esc), TEXT)]
        print(f"\n[i] escaped {name}: {len(hits)} hits -> {hits[:20]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Locate the click-tracker plumbing inside cache/click.patched-widget.js.

The asset never spells "$_CBIT" literally: the name is a decoded string from the
YDbxr string table, reached as obj[<decoder>(<idx>)].  So we:
  1. find the string-table index whose decoded value is $_CBIT / $_CBDL / $_FAA
  2. find every decoder call site using that index
  3. show the surrounding source so we can see where the tracker is created,
     what it is constructed from, and how $_FAA() serialises it.
"""
from __future__ import annotations

import pathlib
import re
import sys

TASK = pathlib.Path(__file__).resolve().parent
ASSET = TASK / "cache" / "click.patched-widget.js"
STRINGS = TASK / "cache" / "click_strings.tsv"

WANT = ["$_CBIT", "$_CBDL", "$_FAA", "$_BJJQ", "$_CBDo", "$_BIDS"]


def load_strings() -> dict[int, str]:
    out: dict[int, str] = {}
    for line in STRINGS.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        try:
            idx = int(parts[0])
        except ValueError:
            continue
        out[idx] = parts[-1]
    return out


def main() -> int:
    strings = load_strings()
    print(f"[i] {len(strings)} decoded strings")
    if strings:
        k = sorted(strings)[0]
        print(f"[i] sample idx={k} -> {strings[k]!r}")

    for name in WANT:
        hits = [i for i, v in strings.items() if v == name]
        print(f"[i] {name}: string-table idx {hits}")

    text = ASSET.read_text(encoding="utf-8", errors="replace")
    # decoder helpers look like $_CGBo(123) / $_CADBN(374) / $_CADAp(751)
    call_re = re.compile(r"\$_[A-Za-z]{3,8}\((\d{1,5})\)")

    for name in WANT:
        idxs = {i for i, v in strings.items() if v == name}
        if not idxs:
            continue
        sites = []
        for m in call_re.finditer(text):
            if int(m.group(1)) in idxs:
                sites.append(m.start())
        print(f"\n=== {name} idx={sorted(idxs)} sites={len(sites)} ===")
        for pos in sites[:24]:
            lo = max(0, pos - 110)
            hi = min(len(text), pos + 90)
            snippet = text[lo:hi].replace("\n", "\\n")
            print(f"  @{pos}: ...{snippet}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())

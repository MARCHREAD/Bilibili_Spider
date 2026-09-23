"""Map the click widget's method table and the pic_type dispatch that builds the
answer tracker.

Findings so far:
  * $_CBIT (idx 824) is the click tracker instance stored on the widget
  * tracker.$_FAA() (idx 469) returns the answer: entries joined with ','
  * each entry is "<x>,<y>" (built by $_BIDk(idx 802): e + ',' + t)
  * $_CAGl(spec) splits spec on '*' then dispatches on widget.pic_type
This script decodes the dispatch cases and dumps the candidate builder bodies.
"""
from __future__ import annotations

import pathlib
import re
import sys

TASK = pathlib.Path(__file__).resolve().parent
ASSET = TASK / "cache" / "click.patched-widget.js"
STRINGS = TASK / "cache" / "click_strings.tsv"
TEXT = ASSET.read_text(encoding="utf-8", errors="replace")
WIDGET_START, WIDGET_LEN = 166932, 16921

IDX = [851, 879, 819, 840, 602, 837, 736, 866, 780, 832, 451, 192, 853, 34,
       826, 108, 170, 313, 456, 138, 48, 956, 987, 87, 940, 8, 899, 700, 39,
       568, 888, 822, 802, 469, 186, 175, 881, 827, 112, 366, 66, 593, 675,
       804, 744, 702, 752, 653, 455, 587, 677, 453, 830, 748, 440, 419, 815,
       568, 617, 662, 147, 176, 785, 710, 717, 739, 771, 773, 764, 621, 497]


def load_strings() -> dict[int, str]:
    out = {}
    for line in STRINGS.read_text(encoding="utf-8", errors="replace").splitlines():
        p = line.split("\t")
        if len(p) >= 2:
            try:
                out[int(p[0])] = p[-1]
            except ValueError:
                pass
    return out


def decode_escapes(s: str) -> str:
    def rep(m):
        return chr(int(m.group(1), 16))
    return re.sub(r"\\u([0-9a-fA-F]{4})", rep, s)


def main() -> int:
    st = load_strings()
    print("=== decoded indices ===")
    for i in sorted(set(IDX)):
        print(f"  {i:4d} -> {st.get(i)!r}")

    print("\n=== widget literal method table (decoded keys) ===")
    body = TEXT[WIDGET_START:WIDGET_START + WIDGET_LEN]
    keys = re.findall(r'"((?:\\u[0-9a-fA-F]{4})+)"\s*:', body)
    print(f"{len(keys)} keys")
    print(", ".join(decode_escapes(k) for k in keys))

    print("\n=== prototype-method assignments inside the literal ===")
    for m in re.finditer(r'\[\$_([A-Za-z]{3,8})\((\d{1,5})\)\]\s*=\s*function', body):
        try:
            idx = int(m.group(2))
        except ValueError:
            continue
        name = st.get(idx)
        if name is None:
            continue
        lo = m.start()
        print(f"  @{WIDGET_START + lo} idx={idx} name={name!r}")

    print("\n=== bodies of the pic_type dispatch targets ===")
    for idx in (837, 804, 802, 186, 175):
        pat = re.compile(r'\[?\$_([A-Za-z]{3,8})\(' + str(idx) + r'\)\]?\s*=\s*function')
        hits = [m for m in pat.finditer(TEXT)]
        print(f"\n--- idx {idx} ({st.get(idx)!r}) assignments: {len(hits)} ---")
        for m in hits[:4]:
            print(TEXT[m.start():m.start() + 900])
    return 0


if __name__ == "__main__":
    sys.exit(main())

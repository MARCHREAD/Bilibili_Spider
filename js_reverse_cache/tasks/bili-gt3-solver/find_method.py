"""Given a source offset, report which escaped-key method encloses it, and dump
that method's opening so we can see how the word-mode click tracker is built.
"""
from __future__ import annotations

import pathlib
import re
import sys

TASK = pathlib.Path(__file__).resolve().parent
TEXT = (TASK / "cache" / "click.patched-widget.js").read_text(
    encoding="utf-8", errors="replace")

KEY_RE = re.compile(r'"((?:\\u[0-9a-fA-F]{4})+)"\s*:\s*function')


def dec(s: str) -> str:
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)


def build_index():
    out = []
    for m in KEY_RE.finditer(TEXT):
        out.append((m.start(), m.end(), dec(m.group(1))))
    return out


def main() -> int:
    keys = build_index()
    print(f"[i] {len(keys)} escaped-key methods")
    probes = [int(a) for a in sys.argv[1:]] or [191671, 193560, 204578, 174112]
    for pos in probes:
        prev = None
        for k in keys:
            if k[0] < pos:
                prev = k
            else:
                break
        if prev is None:
            print(f"\n@{pos}: no enclosing method")
            continue
        nxt = next((k for k in keys if k[0] > prev[0]), None)
        print(f"\n########## @{pos} inside {prev[2]} (key@{prev[0]}) "
              f"len={((nxt[0] if nxt else len(TEXT)) - prev[0])} ##########")
        print(TEXT[prev[1]:prev[1] + 3200])
    return 0


if __name__ == "__main__":
    sys.exit(main())

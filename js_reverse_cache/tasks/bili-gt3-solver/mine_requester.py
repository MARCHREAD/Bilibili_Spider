"""Locate the real JSONP requester j(...) in fullpage.9.2.0. Local only."""
from __future__ import annotations

import pathlib
import re
import sys

ASSET = pathlib.Path(__file__).resolve().parent / "cache" / "fullpage.9.2.0-guwyxh.js"
PATS = [r"j=function\(", r"var j=", r",j=", r"function j\(", r"\bj\("]


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    text = ASSET.read_text(encoding="utf-8", errors="replace")
    for pat in PATS[:4]:
        hits = list(re.finditer(pat, text))
        note(f"\n########## {pat} ({len(hits)}) ##########")
        for m in hits[:6]:
            note(f"@{m.start()}: ...{text[max(0, m.start()-260):m.start()+520]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

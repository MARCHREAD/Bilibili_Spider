"""Find the JSONP/script loader inside fullpage.9.2.0 and its completion latch. Local only."""
from __future__ import annotations

import pathlib
import re
import sys

ASSET = pathlib.Path(__file__).resolve().parent / "cache" / "fullpage.9.2.0-guwyxh.js"
PATS = [
    r"createElement",
    r"appendChild",
    r"408",
    r"onreadystatechange",
    r"readyState",
    r"addEventListener",
]


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    text = ASSET.read_text(encoding="utf-8", errors="replace")
    for pat in PATS:
        hits = list(re.finditer(pat, text))
        note(f"\n########## {pat} ({len(hits)}) ##########")
        for m in hits[:5]:
            note(f"@{m.start()}: ...{text[max(0, m.start()-520):m.start()+320]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

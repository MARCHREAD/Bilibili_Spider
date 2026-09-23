"""Locate the fullpage core-export site (new nt(...)) and $_CDIJ usage. Local only."""
from __future__ import annotations

import pathlib
import re
import sys

ASSET = pathlib.Path(__file__).resolve().parent / "cache" / "fullpage.9.2.0-guwyxh.js"


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    text = ASSET.read_text(encoding="utf-8", errors="replace")
    for pat in [r"new nt\(", r"\$_CDIJ", r"new_le_|\$_\w+\(\d+\)\(window"]:
        hits = list(re.finditer(pat, text))
        note(f"\n########## {pat}  ({len(hits)} hits) ##########")
        for m in hits[:4]:
            note(f"@{m.start()}: ...{text[max(0, m.start()-700):m.start()+400]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

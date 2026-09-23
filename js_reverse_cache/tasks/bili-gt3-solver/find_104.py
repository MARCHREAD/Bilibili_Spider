"""Find the error_104 origin and the Chinese 'request failed' message in fullpage. Local only."""
from __future__ import annotations

import pathlib
import re
import sys

ASSET = pathlib.Path(__file__).resolve().parent / "cache" / "fullpage.9.2.0-guwyxh.js"


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    text = ASSET.read_text(encoding="utf-8", errors="replace")
    needles = ["请求失败", "请保持网络畅通", "请在初始化时传入正确的参数", "error_", "\\u8bf7"]
    for needle in needles:
        hits = list(re.finditer(re.escape(needle), text))
        note(f"\n##### {needle!r}: {len(hits)} hits")
        for m in hits[:3]:
            note(f"  @{m.start()}: ...{text[max(0, m.start()-500):m.start()+300]}...")

    # every bare 104 with a small window, to help spot the error-code table
    hits = [m for m in re.finditer(r"104", text)]
    note(f"\n##### '104' occurrences: {len(hits)}")
    for m in hits[:14]:
        note(f"  @{m.start()}: ...{text[max(0, m.start()-90):m.start()+90]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

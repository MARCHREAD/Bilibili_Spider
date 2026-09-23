"""Find every site that builds a request param object containing "w" (escaped) in fullpage."""
from __future__ import annotations

import pathlib
import re
import sys

ASSET = pathlib.Path(__file__).resolve().parent / "cache" / "fullpage.9.2.0-guwyxh.js"


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    text = ASSET.read_text(encoding="utf-8", errors="replace")
    out_lines: list[str] = []
    patterns = [r'\\u0077":', r'\\u0077\\u0069', r'"w":']
    for pat in patterns:
        hits = list(re.finditer(pat, text))
        out_lines.append(f"##### {pat}: {len(hits)} hits")
        for m in hits[:10]:
            out_lines.append(f"  @{m.start()}: ...{text[max(0, m.start()-420):m.start()+300]}...")
    (ASSET.parent.parent / "w_sites_out.txt").write_text("\n\n".join(out_lines), encoding="utf-8")
    note(f"written {len(out_lines)} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Locate the `w` assembly sites in both products (where the wire payload is built)."""
from __future__ import annotations

import pathlib
import re

TASK = pathlib.Path(__file__).resolve().parent


def main() -> int:
    lines = []
    for name in ("cache/click.3.1.2.js", "cache/fullpage.9.2.0-guwyxh.js"):
        p = TASK / name
        if not p.exists():
            lines.append(f"{name}: missing")
            continue
        t = p.read_text(encoding="utf-8", errors="replace")
        hits = [m.start() for m in re.finditer(r'\\u0077":', t)]
        lines.append(f"=== {name}: w-key sites = {len(hits)}")
        for h in hits[:4]:
            lines.append("  @" + str(h) + ": " + t[max(0, h - 300):h + 200].replace("\n", " "))
        lines.append("")
    (TASK / "w_sites_both.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote w_sites_both.txt ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

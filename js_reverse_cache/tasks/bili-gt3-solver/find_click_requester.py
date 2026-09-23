"""Locate the click product's requester (called as R(widget, url, params)) so a patch can
capture the internal widget object, and check the asset for candidate instantiations."""
from __future__ import annotations

import pathlib
import re

TASK = pathlib.Path(__file__).resolve().parent


def main() -> int:
    t = (TASK / "cache" / "click.3.1.2.js").read_text(encoding="utf-8", errors="replace")
    table: dict[int, str] = {}
    for line in (TASK / "cache" / "click_strings.tsv").read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit():
            table[int(parts[0])] = parts[1]

    out: list[str] = []
    for pat in (r"function R\(", r"[^A-Za-z0-9_$]R=", r"var R=", r",R="):
        hits = [m.start() for m in re.finditer(pat, t)]
        out.append(f"=== {pat}: {len(hits)} hits")
        for h in hits[:3]:
            out.append("  @" + str(h) + ": " + t[max(0, h - 80):h + 700].replace("\n", " ")[:760])
        out.append("")

    # where is the widget object instantiated? look for `new ` calls whose callee is an
    # indexed lookup (oe[$_X(270)] style) and for Object.create
    news = [m.start() for m in re.finditer(r"new [A-Za-z_$][A-Za-z0-9_$]*\(", t)]
    out.append(f"=== plain `new X(` sites: {len(news)} (showing 5 largest-context ones with 6+ args)")
    shown = 0
    for h in news:
        seg = t[h:h + 400]
        if seg.count(",") >= 5:
            out.append("  @" + str(h) + ": " + seg.replace("\n", " ")[:300])
            shown += 1
            if shown >= 5:
                break
    (TASK / "click_requester.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

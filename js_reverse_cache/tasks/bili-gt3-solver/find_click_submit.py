"""Locate the click product's submission site (where '/ajax.php' is used) and dump its
string-index neighbourhood, decoding each index from the exported table."""
from __future__ import annotations

import pathlib
import re

TASK = pathlib.Path(__file__).resolve().parent


def main() -> int:
    asset = (TASK / "cache" / "click.3.1.2.js").read_text(encoding="utf-8", errors="replace")
    table: dict[int, str] = {}
    for line in (TASK / "cache" / "click_strings.tsv").read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit():
            table[int(parts[0])] = parts[1]

    out: list[str] = []
    for idx in (716, 778, 755, 863):
        hits = [m.start() for m in re.finditer(r"\(%d\)" % idx, asset)]
        out.append(f"=== index {idx} ({table.get(idx, '?')!r}) used {len(hits)} times")
        for h in hits[:4]:
            seg = asset[max(0, h - 700):h + 500].replace("\n", " ")
            out.append("  @" + str(h) + ": " + seg)
            idxs = sorted({int(m.group(1)) for m in re.finditer(r"\((\d{1,4})\)", seg)})
            decoded = [(i, table.get(i, "?")) for i in idxs]
            out.append("    indices: " + ", ".join(f"{i}={s[:24]}" for i, s in decoded[:40]))
            out.append("")
        out.append("")
    (TASK / "click_submit_site.txt").write_text("\n".join(out), encoding="utf-8")
    print(f"wrote click_submit_site.txt ({len(out)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

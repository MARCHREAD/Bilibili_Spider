"""Find how the widget's submission method $_BJJQ is invoked: what shape is the answer."""
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

    idxs = [i for i, s in table.items() if s == "$_BJJQ"]
    out = [f"$_BJJQ table indices: {idxs}"]
    for idx in idxs:
        hits = [m.start() for m in re.finditer(r"\(%d\)" % idx, t)]
        out.append(f"=== index {idx} used {len(hits)}x")
        for h in hits[:6]:
            out.append("  @" + str(h) + ": " + t[max(0, h - 420):h + 260].replace("\n", " "))
            out.append("")
    (TASK / "click_bjjq_calls.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)[:3000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

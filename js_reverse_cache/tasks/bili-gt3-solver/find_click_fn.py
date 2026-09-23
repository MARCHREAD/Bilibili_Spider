"""Find the enclosing property name of the click submission site and its guard."""
from __future__ import annotations

import pathlib
import re

TASK = pathlib.Path(__file__).resolve().parent
SITE = 179842


def main() -> int:
    t = (TASK / "cache" / "click.3.1.2.js").read_text(encoding="utf-8", errors="replace")
    table: dict[int, str] = {}
    for line in (TASK / "cache" / "click_strings.tsv").read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].isdigit():
            table[int(parts[0])] = parts[1]

    # walk backwards for the most recent escaped \u0024\u005f property name
    names = [(m.start(), m.group(0)) for m in re.finditer(r'\\u0024\\u005f(?:\\u[0-9a-fA-F]{4})+', t[:SITE])]
    out = []
    if names:
        pos, esc = names[-1]
        name = "".join(chr(int(x, 16)) for x in re.findall(r"\\u([0-9a-fA-F]{4})", esc))
        out.append(f"enclosing property: {name!r} at {pos} (site {SITE}, distance {SITE - pos})")
        head = t[pos:pos + 900]
        out.append("head: " + head.replace("\n", " "))
        idxs = sorted({int(m.group(1)) for m in re.finditer(r"\((\d{1,4})\)", head)})
        out.append("head indices: " + ", ".join(f"{i}={table.get(i, '?')[:26]}" for i in idxs[:40]))
    else:
        out.append("no escaped property name found before the site")

    # decode the plaintext field indices used right around the site
    seg = t[SITE - 400: SITE + 120]
    idxs = sorted({int(m.group(1)) for m in re.finditer(r"\((\d{1,4})\)", seg)})
    out.append("")
    out.append("near-site indices: " + ", ".join(f"{i}={table.get(i, '?')[:30]}" for i in idxs))

    (TASK / "click_submit_fn.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

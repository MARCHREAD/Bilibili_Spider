"""Locate the widget class object literal (containing $_BJJQ) and list its method names."""
from __future__ import annotations

import pathlib
import re

TASK = pathlib.Path(__file__).resolve().parent
SITE = 171443


def main() -> int:
    t = (TASK / "cache" / "click.3.1.2.js").read_text(encoding="utf-8", errors="replace")
    out: list[str] = []

    # bracket-walk backwards to the '{' that opens this literal (strings are short
    # and brace-free in practice for this bundle; validate by printing the context)
    depth = 0
    i = SITE
    start = None
    while i > 0:
        ch = t[i]
        if ch == "}":
            depth += 1
        elif ch == "{":
            if depth == 0:
                start = i
                break
            depth -= 1
        i -= 1
    out.append(f"literal start guess: {start}")
    if start:
        out.append("context before literal: " + t[max(0, start - 160):start + 40].replace("\n", " "))

    # list methods of that literal: scan forward to the matching close
    depth = 0
    end = None
    j = start or SITE
    while j < len(t):
        if t[j] == "{":
            depth += 1
        elif t[j] == "}":
            depth -= 1
            if depth == 0:
                end = j
                break
        j += 1
    out.append(f"literal end guess: {end} (length {(end - start) if start and end else -1})")

    if start and end:
        body = t[start:end]
        names = re.findall(r'"((?:\\u[0-9a-fA-F]{4})+)":function', body)
        decoded = []
        for esc in names:
            dec = "".join(chr(int(x, 16)) for x in re.findall(r"\\u([0-9a-fA-F]{4})", esc))
            decoded.append(dec)
        out.append(f"methods in literal ({len(decoded)}): " + ", ".join(decoded[:60]))
        plain = re.findall(r'([A-Za-z_$][A-Za-z0-9_$]*)":function', body)
        if plain:
            out.append("plain-named methods: " + ", ".join(sorted(set(plain))[:40]))

    (TASK / "click_widget_literal.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

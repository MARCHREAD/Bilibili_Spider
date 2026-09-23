"""Dump the real $_BJJQ (submit) body and decode the indices it uses, so we can see
exactly what goes into `tt` and `ep`.
"""
from __future__ import annotations

import pathlib
import re
import sys

TASK = pathlib.Path(__file__).resolve().parent
TEXT = (TASK / "cache" / "click.patched-widget.js").read_text(encoding="utf-8", errors="replace")
STRINGS = TASK / "cache" / "click_strings.tsv"

WANT = ["$_BJJQ", "$_BHBM", "$_BJK", "$_BIEt", "$_BGIS", "$_CBi", "$_BFDL", "$_BJHe",
        "$_CIU", "$_CCv", "$_JFw", "$_JBl", "$_EJl", "$_BBJ_"]


def load_strings():
    out = {}
    for line in STRINGS.read_text(encoding="utf-8", errors="replace").splitlines():
        p = line.split("\t")
        if len(p) >= 2:
            try:
                out[int(p[0])] = p[-1]
            except ValueError:
                pass
    return out


def dec(s: str) -> str:
    return re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), s)


def main() -> int:
    st = load_strings()
    idx_of = {}
    for name in WANT:
        hits = [i for i, v in st.items() if v == name]
        idx_of[name] = hits
        print(f"{name}: idx {hits}")

    key = "".join("\\u%04x" % ord(c) for c in "$_BJJQ")
    print("\nkey literal:", key)
    for m in re.finditer(re.escape(key), TEXT):
        k = m.start()
        print(f"\n########## $_BJJQ @{k} ##########")
        body = TEXT[k:k + 2200]
        print(body)
        print("\n--- decoded indices in this body ---")
        for mm in re.finditer(r'\$_([A-Za-z]{3,8})\((\d{1,5})\)', body):
            idx = int(mm.group(2))
            print(f"  {idx:5d} -> {st.get(idx)!r}")
        break
    return 0


if __name__ == "__main__":
    sys.exit(main())

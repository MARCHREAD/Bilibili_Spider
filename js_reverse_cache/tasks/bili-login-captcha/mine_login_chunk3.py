"""Mining pass 3: login submit assembly + captcha trigger condition. Local only."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parent
CHUNK = TASK / "raw" / "chunks" / "264.60f4e88f.js"

TARGETS = [
    (r"keeptime", 400, 700),
    (r"showCaptcha", 900, 900),
    (r"captcha-img-dialog|preFunc", 500, 700),
    (r"gee_gt|gee_challenge|recaptcha_type", 300, 500),
    (r"seccode", 500, 700),
    (r"validate:", 400, 700),
]


def note(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def main() -> int:
    text = CHUNK.read_text(encoding="utf-8", errors="replace")
    out: dict = {}

    for pat, left, right in TARGETS:
        ms = list(re.finditer(pat, text))
        wins, seen = [], set()
        for m in ms:
            snip = text[max(0, m.start() - left) : m.end() + right].replace("\n", " ")
            if snip[:60] in seen:
                continue
            seen.add(snip[:60])
            wins.append(f"@{m.start()} ...{snip}...")
            if len(wins) >= 4:
                break
        out[pat] = wins
        note(f"\n########## {pat}  ({len(ms)} hits) ##########")
        for w in wins:
            note(w)

    # explicit error-code neighbourhoods that usually gate a captcha challenge
    for code in ("-105", "-2100", "10000", "-400", "86038", "-509"):
        wins = []
        for m in re.finditer(re.escape(code), text):
            snip = text[max(0, m.start() - 350) : m.end() + 350].replace("\n", " ")
            wins.append(f"@{m.start()} ...{snip}...")
            if len(wins) >= 2:
                break
        if wins:
            out[f"code{code}"] = wins
            note(f"\n########## code {code} ##########")
            for w in wins:
                note(w)

    (TASK / "login_chunk_windows3.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

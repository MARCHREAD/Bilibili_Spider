"""Mining pass 2: pre-fetch, dual captcha channel, login submission assembly. Local only."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parent
CHUNK = TASK / "raw" / "chunks" / "264.60f4e88f.js"

TARGETS = [
    (r"pre_info", 300, 500),
    (r"preCode", 300, 700),
    (r"captcha_url", 200, 700),
    (r"img_code", 300, 500),
    (r"captcha_type", 300, 600),
    (r"/x/passport-login/web/login", 700, 700),
    (r"/x/passport-login/captcha", 500, 800),
    (r"/x/passport-login/web/key", 400, 700),
    (r"getCaptcha|fetchCaptcha|preCaptcha|captcha/pre", 300, 700),
    (r"img_dialog", 200, 400),
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
            if len(wins) >= 3:
                break
        out[pat] = wins
        note(f"\n########## {pat}  ({len(ms)} hits) ##########")
        for w in wins:
            note(w)

    (TASK / "login_chunk_windows2.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

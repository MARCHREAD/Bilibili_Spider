"""Deep-window mining of the login chunk (264) for the geetest wiring. Local only."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parent
CHUNK = TASK / "raw" / "chunks" / "264.60f4e88f.js"

TARGETS = [
    r"gettype\.php",
    r"initGeetest",
    r"geetest_challenge",
    r"new_captcha",
    r"static\.geetest\.com",
    r"/x/passport-login/captcha",
    r"/x/passport-login/web/login",
    r"/x/passport-login/web/key",
    r"geetest_validate",
    r"geetest_seccode",
    r"offline",
    r"product",
    r"captcha_type",
    r"gee_",
    r"captcha_token",
]


def note(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def main() -> int:
    text = CHUNK.read_text(encoding="utf-8", errors="replace")
    out: dict = {"chunk": str(CHUNK), "len": len(text)}

    for pat in TARGETS:
        ms = list(re.finditer(pat, text))
        windows = []
        seen = set()
        for m in ms:
            lo = max(0, m.start() - 420)
            hi = min(len(text), m.end() + 620)
            snip = text[lo:hi].replace("\n", " ")
            if snip[:60] in seen:
                continue
            seen.add(snip[:60])
            windows.append(f"@{m.start()} ...{snip}...")
            if len(windows) >= 3:
                break
        out[pat] = windows
        note(f"\n########## {pat}  ({len(ms)} hits) ##########")
        for w in windows:
            note(w)

    (TASK / "login_chunk_windows.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

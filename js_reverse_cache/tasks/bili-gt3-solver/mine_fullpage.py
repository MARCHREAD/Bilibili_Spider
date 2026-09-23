"""Mine fullpage.9.2.0-guwyxh.js for its patch points and crypto plumbing. Local only."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parent
ASSET = TASK / "cache" / "fullpage.9.2.0-guwyxh.js"

TARGETS = [
    r"function j\(e,t,n\)",
    r"aeskey",
    r"get\.php",
    r"ajax\.php",
    r"gettype\.php",
    r"new nt\(",
    r"\$_CDIJ",
    r"\$_BCm",
    r"window\.Geetest",
    r"initGeetest",
    r"crypt",
    r"RSA",
    r"AES",
    r"CryptoJS",
    r"setPublicKey",
    r"client_type",
    r"passtime",
    r"userresponse",
    r"new_captcha",
]


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    text = ASSET.read_text(encoding="utf-8", errors="replace")
    out: dict = {"asset": ASSET.name, "len": len(text), "markers": {}}

    for pat in TARGETS:
        ms = list(re.finditer(pat, text))
        windows, seen = [], set()
        for m in ms:
            snip = text[max(0, m.start() - 260) : m.end() + 420].replace("\n", " ")
            if snip[:60] in seen:
                continue
            seen.add(snip[:60])
            windows.append({"at": m.start(), "snip": snip})
            if len(windows) >= 3:
                break
        out["markers"][pat] = {"count": len(ms), "windows": windows}
        note(f"\n##### {pat}  ({len(ms)} hits)")
        for w in windows:
            note(f"  @{w['at']} ...{w['snip']}...")

    (TASK / "fullpage_markers.json").write_text(json.dumps(out, ensure_ascii=True, indent=2), encoding="utf-8")
    note("\n=== counts ===")
    note(json.dumps({k: v["count"] for k, v in out["markers"].items()}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

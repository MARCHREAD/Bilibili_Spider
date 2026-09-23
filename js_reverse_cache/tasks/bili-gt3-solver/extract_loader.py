"""Extract the inlined geetest loader (gt.js) from the bilibili passport chunk.

Evidence-based: bilibili inlines the official loader into its own chunk, so we
reuse exactly the bytes the site ships instead of guessing a CDN filename.
Local only.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parent
SRC = TASK.parent / "bili-login-captcha" / "raw" / "chunks" / "264.60f4e88f.js"
OUT = TASK / "cache" / "gt_loader_from_bili.js"

MARK = '!function(t){if(void 0===t)throw Error("Geetest requires browser environment")'


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    text = SRC.read_text(encoding="utf-8", errors="replace")
    start = text.find(MARK)
    if start < 0:
        note("[fail] loader mark not found")
        return 1

    end_mark = "}(window);"
    end = text.find(end_mark, start)
    if end < 0:
        note("[fail] loader end mark not found")
        return 1
    end += len(end_mark)
    loader = text[start:end]

    checks = {
        "initGeetest": "initGeetest" in loader,
        "gettype.php": "/gettype.php" in loader,
        "api.geetest.com": "api.geetest.com" in loader,
        "new t.Geetest": "Geetest" in loader,
        "fallback_config": "fallback_config" in loader,
    }
    OUT.write_text(loader, encoding="utf-8")
    info = {
        "source": str(SRC),
        "offset": start,
        "length": len(loader),
        "sha256": hashlib.sha256(loader.encode()).hexdigest(),
        "checks": checks,
        "tail": loader[-60:],
    }
    note(f"[loader] {len(loader)}B offset={start} sha256={info['sha256'][:16]} checks={checks}")
    (TASK / "cache" / "gt_loader_manifest.json").write_text(json.dumps(info, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in info.items() if k != "tail"}, ensure_ascii=True))
    return 0 if all(checks.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())

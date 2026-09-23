"""Fetch the current GT3 SDK assets for the pure-algorithm workbench. GET only.

The asset names come from the live gettype.php response captured for bilibili:
  fullpage.9.2.0-guwyxh.js / slide.7.9.3.js / geetest.6.0.9.js
Assets are saved raw (never hand-edited) plus a sha256 manifest, because the
final helper must run the raw current asset.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

from curl_cffi import requests

TASK = Path(__file__).resolve().parent
CACHE = TASK / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

ASSETS = [
    "https://static.geetest.com/static/js/fullpage.9.2.0-guwyxh.js",
    "https://static.geetest.com/static/js/slide.7.9.3.js",
    "https://static.geetest.com/static/js/geetest.6.0.9.js",
]


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    s = requests.Session(impersonate="chrome146")
    s.headers.update({"Referer": "https://passport.bilibili.com/login", "Accept-Language": "zh-CN,zh;q=0.9"})
    manifest = []
    for url in ASSETS:
        name = url.rsplit("/", 1)[-1]
        time.sleep(0.4)
        r = s.get(url, timeout=40)
        data = r.content
        (CACHE / name).write_bytes(data)
        entry = {
            "url": url,
            "file": name,
            "status": r.status_code,
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "content_type": r.headers.get("content-type"),
        }
        manifest.append(entry)
        with (TASK / "network.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"probe": f"asset_{name}", "url": url, "status": r.status_code, "len": len(data)}) + "\n")
        note(f"[asset] {name} {r.status_code} {len(data)}B sha256={entry['sha256'][:16]}")

    (TASK / "asset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

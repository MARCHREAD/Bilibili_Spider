"""Fetch the 8 passport async chunks and locate the captcha consumer. GET only."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from curl_cffi import requests

TASK = Path(__file__).resolve().parent
RAW = TASK / "raw" / "chunks"
RAW.mkdir(parents=True, exist_ok=True)
IMPERSONATE = "chrome146"
BASE = "https://s1.hdslb.com/bfs/static/2233-monorepo/passport/static/js/async/"
# id -> hash, lifted from the rsbuild manifest in index.ed509056.js
CHUNKS = {
    10: "85831162",
    263: "9c8b9071",
    264: "60f4e88f",
    409: "968ce5e0",
    600: "5812ee4e",
    832: "5b9896d7",
    838: "b9d2ec25",
    86: "7f85abb2",
}
NEEDLES = (
    "geetest",
    "static.geetest.com",
    "gt.js",
    "geetest_challenge",
    "geetest_validate",
    "geetest_seccode",
    "gettype.php",
    "get.php",
    "ajax.php",
    "captcha",
    "/x/passport-login/",
    "register-slide",
    "fullpage",
    "slide",
    "risk",
    "challenge",
)


def note(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def main() -> int:
    session = requests.Session(impersonate=IMPERSONATE)
    session.headers["Referer"] = "https://passport.bilibili.com/login"
    report: dict = {"chunks": {}}

    for cid, chash in CHUNKS.items():
        url = f"{BASE}{cid}.{chash}.js"
        time.sleep(0.4)
        resp = session.get(url, timeout=40)
        body = resp.text
        path = RAW / f"{cid}.{chash}.js"
        path.write_text(body, encoding="utf-8", errors="replace")
        with (TASK / "network.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"probe": f"chunk_{cid}", "url": url, "status": resp.status_code, "len": len(body)}) + "\n")

        hits = {n: len(re.findall(re.escape(n), body, re.I)) for n in NEEDLES}
        hits = {k: v for k, v in hits.items() if v}
        routes = sorted(set(re.findall(r"[\"'`](/x/[A-Za-z0-9_/\-{}]+)", body)))
        gee_urls = sorted(set(re.findall(r"[\"'`]([^\"'`]*(?:geetest|gt)[^\"'`]*\.js[^\"'`]*)", body, re.I)))
        report["chunks"][str(cid)] = {
            "url": url,
            "status": resp.status_code,
            "len": len(body),
            "hits": hits,
            "routes": routes[:40],
            "geetest_urls": gee_urls[:10],
        }
        note(f"[chunk {cid}] {resp.status_code} {len(body)}B hits={hits}")
        if routes:
            note(f"   routes={routes[:14]}")
        if gee_urls:
            note(f"   gee_urls={gee_urls[:6]}")

    (TASK / "chunk_findings.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

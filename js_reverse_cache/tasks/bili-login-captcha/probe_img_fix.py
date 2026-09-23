"""Finish the control set: binary-correct image capture + JSON-safe summary. GET only."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from curl_cffi import requests

TASK = Path(__file__).resolve().parent
RAW = TASK / "raw"


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    s = requests.Session(impersonate="chrome146")
    s.headers.update({"Accept-Language": "zh-CN,zh;q=0.9", "Referer": "https://passport.bilibili.com/login"})
    out: dict = {}

    # no-token control (JSON error)
    time.sleep(0.4)
    r = s.get(f"https://api.bilibili.com/x/recaptcha/img?_={int(time.time()*1000)}", timeout=25)
    out["img_no_token"] = {"status": r.status_code, "content_type": r.headers.get("content-type"), "json": r.json()}
    (RAW / "recaptcha_img_no_token.json").write_bytes(r.content)

    # bogus-token control (still an image -> the endpoint needs a token *present*, not valid)
    time.sleep(0.4)
    r2 = s.get(
        f"https://api.bilibili.com/x/recaptcha/img?_={int(time.time()*1000)}&token=deadbeefdeadbeefdeadbeefdeadbeef",
        timeout=25,
    )
    body = r2.content
    (RAW / "recaptcha_img_bogus_token.jpg").write_bytes(body)
    out["img_bogus_token"] = {
        "status": r2.status_code,
        "content_type": r2.headers.get("content-type"),
        "bytes": len(body),
        "is_jpeg": body[:2] == b"\xff\xd8",
    }
    out["budget_note"] = "2 requests; total probes recorded in network.jsonl"

    (TASK / "control_probes.json").write_text(
        json.dumps(out, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

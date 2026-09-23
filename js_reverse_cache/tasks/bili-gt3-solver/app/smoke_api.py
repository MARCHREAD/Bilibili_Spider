"""Smoke-test the local debug API: start a run, poll it, fetch the round image.

usage: python app/smoke_api.py [port]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8795
BASE = f"http://127.0.0.1:{PORT}"


def get(path: str):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def post(path: str, body: dict):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    print("health:", json.dumps(get("/api/health"), ensure_ascii=True))
    run = post("/api/run", {"rounds": 1})
    run_id = run["run_id"]
    print("started run", run_id)

    log_from, deadline = 0, time.time() + 300
    last = None
    while time.time() < deadline:
        st = get(f"/api/run/{run_id}?log_from={log_from}")
        for line in st.get("log") or []:
            print("   |", line[:150])
        log_from = st.get("log_total", log_from)
        last = st
        if st.get("status") != "running":
            break
        time.sleep(1.5)

    print("\n--- summary ---")
    for k in ("status", "ok", "challenge", "prompt", "n_clicks", "points", "wire_answer",
              "validate", "score", "http_used", "pic", "log_total"):
        print(f"  {k}: {json.dumps(last.get(k), ensure_ascii=True)}")
    print("  w_values:", json.dumps(last.get("w_values"), ensure_ascii=True))
    print("  verdict:", json.dumps(last.get("verdict"), ensure_ascii=True))

    pic = last.get("pic")
    if pic:
        url = f"{BASE}/api/image/{run_id}/{pic}"
        with urllib.request.urlopen(url, timeout=30) as r:
            blob = r.read()
            print(f"  image: {r.status} {len(blob)} bytes  ({url})")
    return 0 if last.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())

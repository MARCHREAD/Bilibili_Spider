"""单接口快速校验：python probe_one.py <kind> <target> [json-options]"""

from __future__ import annotations

import json
import sys
import urllib.request

PORT = 8765


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else "user"
    target = sys.argv[2] if len(sys.argv) > 2 else "480959917"
    options = json.loads(sys.argv[3]) if len(sys.argv) > 3 else {}
    body = json.dumps({"kind": kind, "target": target, "options": options}).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/call", data=body,
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        out = json.loads(resp.read().decode("utf-8"))
    if not out.get("ok"):
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1
    data = out["data"]
    if kind == "user":
        keys = ("uid", "name", "sign", "level", "following", "follower", "video_count",
                "dynamic_count", "dynamic_count_method", "likes", "play", "charging_count",
                "privacy", "errors")
        data = {k: data.get(k) for k in keys if k in data}
    if kind == "video":
        pc = data.get("pinned_comment") or {}
        data = {
            "bvid": data.get("bvid"),
            "ad_verdict": data.get("ad_verdict"),
            "pinned_source": pc.get("pinned_source"),
            "pinned_found": bool(pc),
            "pinned_rpid": pc.get("rpid"),
            "pinned_mid": pc.get("mid"),
            "pinned_uname": (pc.get("member") or {}).get("uname"),
            "pinned_message": (pc.get("message") or "")[:220],
            "pinned_links": pc.get("links"),
            "promo": data.get("promo"),
        }
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

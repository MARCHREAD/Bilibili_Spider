"""账号诊断：打印账号列表与单账号校验的完整返回。"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8765"


def req(path: str, payload=None, method=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    r = urllib.request.Request(BASE + path, data=data,
                               headers={"Content-Type": "application/json"} if data else {},
                               method=method or ("POST" if data is not None else "GET"))
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    st = req("/api/status")
    if not st.get("ok"):
        print("status 失败:", st, file=sys.stderr)
        return 1
    d = st["data"]
    print("== accounts ==", file=sys.stderr)
    print(json.dumps(d["accounts"], ensure_ascii=False, indent=2), file=sys.stderr)
    print("== security ==", file=sys.stderr)
    print(json.dumps(d.get("security"), ensure_ascii=False), file=sys.stderr)
    if not d["accounts"]:
        return 1
    aid = d["accounts"][0]["id"]
    print(f"== verify account {aid} ==", file=sys.stderr)
    v = req(f"/api/accounts/{aid}/verify", {})
    print(json.dumps(v, ensure_ascii=False, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

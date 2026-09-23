"""显示本地工作台与多账号状态。

用法：
    python tests/session_status.py            # 看服务 / 账号 / worker / 存储
    python tests/session_status.py --verify   # 顺便校验所有账号
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def call(base: str, path: str, payload=None, method: str | None = None, timeout: int = 180):
    data = json.dumps(payload).encode() if payload is not None else None
    verb = method or ("POST" if data is not None else "GET")
    req = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": "application/json"} if data else {}, method=verb)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--verify", action="store_true", help="顺便校验所有账号")
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    st = call(base, "/api/status")
    if not st.get("ok"):
        print(f"服务未就绪: {st.get('error')}", file=sys.stderr)
        print("请先运行:  python main.py", file=sys.stderr)
        return 1
    d = st["data"]

    print(f"服务      : v{d['version']}  http://127.0.0.1:{args.port}/", file=sys.stderr)
    print(f"并发      : workers={d['workers']['workers']} "
          f"运行中={d['workers']['running']} 排队={d['workers']['queued']}", file=sys.stderr)
    print(f"存储      : 任务 {d['store']['jobs']} · 记录 {d['store']['records']} · "
          f"midHash 字典 {d['store']['midhash_index']}", file=sys.stderr)
    sec = d.get("security") or {}
    print(f"凭证加密  : {sec.get('backend')} — {sec.get('note')}", file=sys.stderr)

    accounts = d.get("accounts") or []
    print(f"\n账号（{len(accounts)} 个，健康 {d['healthy_count']} 个）：", file=sys.stderr)
    if not accounts:
        print("  （无）请在界面右上角「+ 添加账号」", file=sys.stderr)
    for a in accounts:
        flag = "OK " if a.get("last_status") == "ok" else "-- "
        print(f"  {flag}#{a['id']:<3} {a['alias']:<14} "
              f"{(a.get('uname') or '(未登录)'):<12} uid={str(a.get('mid') or '-'):<12} "
              f"方式={a.get('login_method')} cookie={a.get('has_cookie')} "
              f"密码={a.get('has_password')}", file=sys.stderr)

    if args.verify and accounts:
        print("\n校验所有账号…", file=sys.stderr)
        va = call(base, "/api/accounts/verify-all", {})
        if not va.get("ok"):
            print(f"  失败: {va.get('error')}", file=sys.stderr)
        else:
            for r in va["data"]:
                print(f"  {'OK ' if r.get('ok') else 'BAD'} {r.get('alias'):<14} "
                      f"{(r.get('uname') or r.get('error') or '')}", file=sys.stderr)

    print(json.dumps({"accounts": accounts,
                      "workers": d["workers"], "store": d["store"],
                      "security": sec}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

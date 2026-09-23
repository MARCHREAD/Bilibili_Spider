"""多账号 + 多 worker 专项验证。

用法：python tests/test_accounts.py [--port 8765]

会临时创建一个测试账号副本（用本地 session.txt 的 cookie），跑完删除。
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
SESSION = ROOT / "data" / "session.txt"
PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK ] {label:<44} {detail}", file=sys.stderr)
    else:
        FAIL += 1
        print(f"  [BAD] {label:<44} {detail}", file=sys.stderr)


def call(base: str, path: str, payload=None, method: str | None = None, timeout: int = 300):
    """method=None 时：带 body 用 POST，不带 body 用 GET（DELETE 必须显式传）。"""
    data = json.dumps(payload).encode() if payload is not None else None
    verb = method or ("POST" if data is not None else "GET")
    req = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method=verb)
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


def wait_job(base: str, job_id: int, limit: int = 120) -> dict:
    for _ in range(limit):
        body = call(base, f"/api/jobs/{job_id}", method="GET")
        if body.get("ok") and body["data"]["status"] in ("finished", "cancelled", "failed"):
            return body["data"]
        time.sleep(1.5)
    return call(base, f"/api/jobs/{job_id}", method="GET").get("data", {})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    print("== 账号基础 ==", file=sys.stderr)
    st = call(base, "/api/status", method="GET")
    check("服务在线", st.get("ok"), str(st.get("error", "")))
    if not st.get("ok"):
        return 1
    d = st["data"]
    check("已有账号（旧会话已迁移）", d["account_count"] >= 1,
          f"count={d['account_count']}")
    check("worker 状态可用", "workers" in d, json.dumps(d.get("workers")))
    check("凭证已加密后端就绪", bool(d.get("security", {}).get("backend")),
          json.dumps(d.get("security"), ensure_ascii=False))
    accounts = d["accounts"]
    check("账号列表不含 cookie 明文",
          all("cookie" not in json.dumps(a) or a.get("cookie_hint", "").count("*") >= 0
              for a in accounts),
          "cookie_hint=" + str([a.get("cookie_hint") for a in accounts]))
    check("账号列表给出凭证存在性标记",
          all("has_cookie" in a and "has_password" in a for a in accounts))

    primary = accounts[0]["id"]
    print("== 单账号校验 ==", file=sys.stderr)
    v = call(base, f"/api/accounts/{primary}/verify", {}, method="POST")
    check("主账号校验", v.get("ok") and v.get("data", {}).get("ok"),
          json.dumps(v.get("data") or v, ensure_ascii=False)[:170])

    print("== 多账号：创建副本 ==", file=sys.stderr)
    temp_id = None
    if SESSION.exists():
        cookie = SESSION.read_text(encoding="utf-8").strip()
        created = call(base, "/api/accounts",
                       {"alias": "__测试副本__", "login_method": "cookie", "cookie": cookie})
        if created.get("ok"):
            temp_id = created["data"]["id"]
            check("创建第二个账号", True, f"id={temp_id}")
            check("创建后不回传 cookie", "cookie" not in created["data"]
                  or created["data"].get("has_cookie") is True)
        else:
            check("创建第二个账号", False, created.get("error", ""))
    else:
        check("本地 session.txt 存在（用于建副本）", False, str(SESSION))

    if temp_id:
        print("== 并行校验全部账号 ==", file=sys.stderr)
        t0 = time.time()
        va = call(base, "/api/accounts/verify-all", {})
        dt = time.time() - t0
        check("verify-all 返回", va.get("ok"), f"{len(va.get('data') or [])} 个账号 {dt:.1f}s")
        if va.get("ok"):
            oks = [r for r in va["data"] if r.get("ok")]
            check("两个账号均有效", len(oks) >= 2,
                  ", ".join(f"{r.get('alias')}={'ok' if r.get('ok') else r.get('error')}"
                            for r in va["data"]))
            check("并行校验比串行快（< 2×单次）", dt < 60, f"{dt:.1f}s")

        print("== worker 数运行时调整 ==", file=sys.stderr)
        w = call(base, "/api/workers", {"workers": 4})
        check("调到 4", w.get("ok") and w["data"]["workers"] == 4,
              json.dumps(w.get("data", {}).get("workers")))
        w = call(base, "/api/workers", {"workers": 2})
        check("调回 2", w.get("ok") and w["data"]["workers"] == 2,
              json.dumps(w.get("data", {}).get("workers")))
        check("非法值被拒", not call(base, "/api/workers", {"workers": 99}).get("ok"))

        print("== 多账号分片并行任务 ==", file=sys.stderr)
        job = call(base, "/api/jobs", {
            "kind": "video", "targets": ["BV1BHez6cEEm", "BV1X9eb6tEvy"],
            "options": {"with_subtitle": False, "with_tags": False,
                        "with_pinned_comment": True},
            "shard": True,
        })
        check("创建分片任务", job.get("ok"), str(job.get("error", "")))
        if job.get("ok"):
            jd = wait_job(base, job["data"]["job_id"])
            check("分片任务完成", jd.get("status") == "finished",
                  f"status={jd.get('status')} done={jd.get('done')} failed={jd.get('failed')}")
            check("全部目标成功", jd.get("done") == 2 and jd.get("failed") == 0,
                  f"done={jd.get('done')} failed={jd.get('failed')}")
            check("标记为分片任务", jd.get("shard") == 1, str(jd.get("shard")))

        print("== 指定账号的单次调用 ==", file=sys.stderr)
        r = call(base, "/api/call", {"kind": "video", "target": "BV1BHez6cEEm",
                                     "options": {"with_subtitle": False, "with_tags": False,
                                                 "with_pinned_comment": False},
                                     "account_id": temp_id})
        check("指定账号调用成功", r.get("ok"), str(r.get("error", "")))

        print("== 清理 ==", file=sys.stderr)
        dele = call(base, f"/api/accounts/{temp_id}", method="DELETE")
        check("删除测试账号", dele.get("ok") and dele["data"].get("deleted"),
              json.dumps(dele.get("data")))
        after = call(base, "/api/status", method="GET")["data"]["account_count"]
        check("账号数回落", after == d["account_count"], f"{after}")

    print(f"\n{PASS} passed, {FAIL} failed", file=sys.stderr)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

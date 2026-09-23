"""端到端验收：通过工作台 API 提交真实的 search 批量任务，检查失败率。

这是最贴近用户场景的验证 —— 走完整的 JobRunner → AccountPool(新 client，创建即
bootstrap) → BiliClient.request_json（软风控独立预算 + 自愈）链路。

用法：python tests/verify_search_job.py [--base http://127.0.0.1:8765] [--targets 8]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

KEYWORDS = ["原神", "崩坏3", "王者荣耀", "和平精英", "我的世界",
            "艾尔登法环", "塞尔达传说", "黑神话悟空", "绝区零", "鸣潮",
            "明日方舟", "赛博朋克2077"]


def call(base: str, path: str, payload=None, method: str | None = None, timeout: int = 60):
    data = json.dumps(payload).encode() if payload is not None else None
    verb = method or ("POST" if data is not None else "GET")
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {},
                                 method=verb)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8765")
    ap.add_argument("--targets", type=int, default=8)
    ap.add_argument("--page", type=int, default=1)
    args = ap.parse_args()

    targets = KEYWORDS[:args.targets]
    body = call(args.base, "/api/jobs", {
        "kind": "search", "targets": targets,
        "options": {"page": args.page, "page_size": 30, "order": "totalrank"},
    })
    if not body.get("ok"):
        print("提交失败:", json.dumps(body, ensure_ascii=False))
        return 1
    job_id = body["data"]["job_id"]
    print(f"job_id={job_id} targets={targets}", flush=True)

    t0 = time.time()
    last = None
    for _ in range(240):
        job = call(args.base, f"/api/jobs/{job_id}", timeout=30)["data"]
        snap = (job["status"], job["done"], job["failed"])
        if snap != last:
            print(f"  [{time.time() - t0:6.1f}s] status={job['status']} "
                  f"done={job['done']}/{job['total']} failed={job['failed']}", flush=True)
            last = snap
        if job["status"] in ("finished", "failed", "cancelled", "interrupted"):
            break
        time.sleep(1.5)

    print("\n== 每个 target 的结果 ==")
    bad = 0
    for r in job.get("results") or []:
        ok = r.get("ok")
        if not ok:
            bad += 1
        payload = r.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:  # noqa: BLE001
                payload = None
        n = len((payload or {}).get("items") or []) if isinstance(payload, dict) else None
        page = (payload or {}).get("api_page") if isinstance(payload, dict) else None
        print(f"  {'OK  ' if ok else 'FAIL'} {r['target']:<14} items={n} api_page={page} "
              f"{(r.get('error') or '')[:80]}")
    print(f"\n结论: status={job['status']} done={job['done']}/{job['total']} "
          f"failed={job['failed']} 耗时 {time.time() - t0:.0f}s")
    return 0 if job["failed"] == 0 and job["done"] == job["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

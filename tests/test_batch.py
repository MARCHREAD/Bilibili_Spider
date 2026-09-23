"""批量任务验证：创建任务 -> 轮询 -> 校验落库 -> 验证断点续跑。

用法：python tests/test_batch.py [--port 8765]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

TARGETS = ["BV1BHez6cEEm", "BV1X9eb6tEvy"]


def call(base: str, path: str, payload: dict | None = None, timeout: int = 120):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        base + path, data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data else "GET")
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


def wait_job(base: str, job_id: int, limit: int = 90) -> dict:
    for _ in range(limit):
        body = call(base, f"/api/jobs/{job_id}")
        if not body.get("ok"):
            return {"status": "error", "error": body.get("error")}
        job = body["data"]
        if job["status"] in ("finished", "cancelled"):
            return job
        time.sleep(2)
    return call(base, f"/api/jobs/{job_id}")["data"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    base = f"http://127.0.0.1:{args.port}"

    passed = failed = 0

    def check(label: str, ok: bool, detail: str = ""):
        nonlocal passed, failed
        if ok:
            passed += 1
            print(f"  [OK ] {label:<40} {detail}", file=sys.stderr)
        else:
            failed += 1
            print(f"  [BAD] {label:<40} {detail}", file=sys.stderr)

    print("== 批量任务: 视频详情 x2 ==", file=sys.stderr)
    body = call(base, "/api/jobs", {"kind": "video", "targets": TARGETS,
                                    "options": {"with_subtitle": False, "with_tags": True,
                                                "with_pinned_comment": True}})
    check("创建任务", body.get("ok"), str(body.get("error", "")))
    if not body.get("ok"):
        return 1
    job_id = body["data"]["job_id"]
    job = wait_job(base, job_id)
    check("任务完成", job.get("status") == "finished", f"status={job.get('status')}")
    check("全部目标成功", job.get("done") == len(TARGETS) and job.get("failed") == 0,
          f"done={job.get('done')} failed={job.get('failed')}")
    results = job.get("results") or []
    check("结果条数正确", len(results) == len(TARGETS), f"{len(results)}")
    for r in results:
        v = (r.get("payload") or {}).get("ad_verdict") or {}
        check(f"  {r['target']} 判定", bool(v.get("category")), f"{v.get('category')}")

    print("== 断点续跑: 重复提交同 kind+options ==", file=sys.stderr)
    body2 = call(base, "/api/jobs", {"kind": "video", "targets": TARGETS,
                                     "options": {"with_subtitle": False, "with_tags": True,
                                                 "with_pinned_comment": True}})
    check("重复提交成功", body2.get("ok"))
    job2 = wait_job(base, body2["data"]["job_id"])
    check("新任务同样完成", job2.get("status") == "finished",
          f"done={job2.get('done')} failed={job2.get('failed')}")

    print("== 批量任务: 弹幕 ==", file=sys.stderr)
    body3 = call(base, "/api/jobs", {"kind": "danmaku", "targets": TARGETS,
                                     "options": {"all_segments": True}})
    job3 = wait_job(base, body3["data"]["job_id"])
    check("弹幕任务完成", job3.get("status") == "finished" and job3.get("failed") == 0,
          f"done={job3.get('done')} failed={job3.get('failed')}")
    for r in job3.get("results") or []:
        cov = (r.get("payload") or {}).get("coverage") or {}
        check(f"  {r['target']} 弹幕覆盖", (r.get("payload") or {}).get("count", 0) > 0,
              f"count={(r.get('payload') or {}).get('count')} "
              f"stat={cov.get('stat_danmaku')} complete={cov.get('complete')}")

    print("== 弹幕发送者还原（候选池不能为空 + 计数自洽）==", file=sys.stderr)
    body5 = call(base, "/api/call", {"kind": "danmaku", "target": TARGETS[0],
                                     "options": {"all_segments": True,
                                                 "resolve_senders": True,
                                                 "pool_pages": 3}})
    if body5.get("ok"):
        data5 = body5["data"]
        idn = data5.get("identity") or {}
        check("候选池非空（曾因 aid 解析失败恒为 0）",
              idn.get("candidate_pool", 0) > 0,
              f"pool={idn.get('candidate_pool')} source={idn.get('pool_source')}")
        check("标记为支持还原", idn.get("supported") is True)
        check("resolved + unresolved == 弹幕条数",
              idn.get("resolved", 0) + idn.get("unresolved", 0) == data5.get("count"),
              f"{idn.get('resolved')} + {idn.get('unresolved')} vs {data5.get('count')}")
        check("默认不还原时 supported 为 False（不白跑请求）",
              (call(base, "/api/call", {"kind": "danmaku", "target": TARGETS[0],
                                        "options": {"all_segments": True}}
                    ).get("data", {}).get("identity", {}).get("supported") is False))
    else:
        check("弹幕还原调用", False, body5.get("error", ""))

    print("== 落库校验 ==", file=sys.stderr)
    recs = call(base, "/api/records?limit=20")
    check("records 有数据", recs.get("ok") and len(recs["data"]) >= len(TARGETS),
          f"{len(recs.get('data') or [])} 条")
    kinds = {r["kind"] for r in recs.get("data") or []}
    check("落库含 video 与 danmaku", {"video", "danmaku"} <= kinds, str(sorted(kinds)))

    print("== 失败隔离 ==", file=sys.stderr)
    body4 = call(base, "/api/jobs", {"kind": "video",
                                     "targets": ["BV1BHez6cEEm", "BV0000000000"],
                                     "options": {"with_subtitle": False}})
    job4 = wait_job(base, body4["data"]["job_id"])
    check("坏目标不拖垮整个任务",
          job4.get("status") == "finished" and job4.get("done") == 1 and job4.get("failed") == 1,
          f"done={job4.get('done')} failed={job4.get('failed')}")

    print(f"\n{passed} passed, {failed} failed", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

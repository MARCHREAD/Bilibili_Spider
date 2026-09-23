"""搜索深分页边界探针：page 超过 numPages 时，服务端到底回什么？

假设：搜索接口的"越界页"不是返回空列表，而是用 v_voucher 软风控回应。
如果是这样，批量任务里 page 设大了就会**反复撞软风控**（这正是"页数上去容易触发"）。

方法：按 page 分层、轮次在外层的交替采样，消除时间趋势。
  1. 先取 page=1 拿到 numPages（接口上限）
  2. 对 1 / 上限内末页 / 上限+1 / 上限+5 / 远超上限 各采样 N 次

用法：python tests/probe_search_paging_bound.py [--account 1] [--rounds 4]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb import constants as C
from biliwb.accounts import AccountPool
from biliwb.store import Store

OUT = ROOT / "tests" / "_paging"
OUT.mkdir(exist_ok=True)

BASE = {
    "search_type": "video", "keyword": "原神", "order": "totalrank",
    "page_size": 30, "duration": 0, "from_source": "", "web_location": 1430654,
}


def probe(cli, page: int) -> tuple[str, dict]:
    params = dict(BASE, page=page)
    body = cli.request_json(C.EP_SEARCH_TYPE, params=params, wbi=True, soft=True,
                            retries=0,
                            headers={"Referer": "https://search.bilibili.com/"})
    data = (body or {}).get("data")
    meta = {"page": page, "code": (body or {}).get("code")}
    if not isinstance(data, dict):
        return "ERROR-shape", meta
    meta["data_keys"] = sorted(data)[:8]
    if "v_voucher" in data:
        meta["v_voucher"] = str(data["v_voucher"])[:20]
        return "SOFT-RISK", meta
    res = data.get("result")
    meta["result_len"] = len(res) if isinstance(res, list) else None
    meta["numResults"] = data.get("numResults")
    meta["numPages"] = data.get("numPages")
    meta["api_page"] = data.get("page")
    if isinstance(res, list) and res:
        return "OK", meta
    return "EMPTY", meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=int, default=None)
    ap.add_argument("--rounds", type=int, default=4)
    args = ap.parse_args()

    store = Store(ROOT / "data" / "biliwb.db")
    pool = AccountPool(store, data_dir=ROOT / "data")
    aid = args.account or pool.pick()
    api = pool.api(aid)
    cli = pool.client(aid)

    # 1) 先确定接口给出的页数上限（多取几次，取最常见值，避免被单次软风控带偏）
    upper = None
    for _ in range(6):
        verdict, meta = probe(cli, 1)
        if verdict == "OK":
            upper = meta.get("numPages")
            print(f"page=1 -> OK numResults={meta.get('numResults')} numPages={upper}",
                  flush=True)
            break
        print(f"page=1 -> {verdict}（重试以取得上限）", flush=True)
    if not upper:
        print("无法取得 numPages，放弃")
        store.close()
        return 1

    pages = [1, max(1, upper - 1), upper, upper + 1, upper + 5, upper * 3]
    pages = sorted(set(pages))
    print(f"采样页: {pages}（接口上限 numPages={upper}）", flush=True)

    rows: dict[int, list[str]] = {p: [] for p in pages}
    details: list[dict] = []
    for r in range(args.rounds):
        for p in pages:
            verdict, meta = probe(cli, p)
            rows[p].append(verdict)
            details.append(meta)
            print(f"  round{r + 1} page={p:<4} -> {verdict:<10} keys={meta.get('data_keys')}",
                  flush=True)

    print("\n== 按页汇总 ==")
    summary = {}
    for p in pages:
        vals = rows[p]
        soft = sum(1 for v in vals if v == "SOFT-RISK")
        summary[p] = {"soft_risk": soft, "n": len(vals),
                      "rate": round(soft / max(1, len(vals)), 2), "verdicts": vals,
                      "above_upper": p > upper}
        tag = "越界" if p > upper else "界内"
        print(f"  page={p:<4} [{tag}] soft_risk={soft}/{len(vals)}  {vals}")

    (OUT / f"bound_{int(time.time())}.json").write_text(
        json.dumps({"account": aid, "numPages": upper, "summary": summary,
                    "details": details}, ensure_ascii=False, indent=2), encoding="utf-8")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

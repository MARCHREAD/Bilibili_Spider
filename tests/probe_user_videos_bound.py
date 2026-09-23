"""越界页一致性探针：搜索与作者投稿列表在 page/pn 超出范围时的行为。

两个问题：
  1. `x/web-interface/wbi/search/type` 请求 page > numPages 时是否会回退 page？
     （已实测会：page=39 -> api_page=1，拿到的是**别的页**的数据）
  2. 修好之后的 search_videos 是否会明确报错而不是把别的页当成本页？
  3. `x/space/wbi/arc/search`（作者投稿，pn 参数）是否有同样的问题？

用法：python tests/probe_user_videos_bound.py [--account 1] [--uid 86889715]
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
from biliwb.client import gaia_slots
from biliwb.store import Store

OUT = ROOT / "tests" / "_paging"
OUT.mkdir(exist_ok=True)


def arc_search(cli, uid: int, pn: int, ps: int = 30) -> dict:
    body = cli.request_json(
        C.EP_ARC_SEARCH,
        params={"mid": uid, "pn": pn, "ps": ps, "tid": 0, "special_type": "",
                "order": "pubdate", "index": 0, "keyword": "",
                "order_avoided": "true", "platform": "web",
                "web_location": 333.1387, **gaia_slots()},
        wbi=True, soft=True, retries=0,
        headers={"Referer": f"https://space.bilibili.com/{uid}/upload/video"})
    data = (body or {}).get("data") or {}
    if "v_voucher" in data:
        return {"pn": pn, "soft_risk": True}
    page = data.get("page") or {}
    vlist = ((data.get("list") or {}).get("vlist")) or []
    return {
        "pn": pn,
        "soft_risk": False,
        "api_pn": page.get("pn"),
        "count": page.get("count"),
        "vlist_len": len(vlist),
        "first_bvid": (vlist[0] or {}).get("bvid") if vlist else None,
        "same_page": page.get("pn") == pn,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=int, default=None)
    ap.add_argument("--uid", type=int, default=86889715)
    args = ap.parse_args()

    store = Store(ROOT / "data" / "biliwb.db")
    pool = AccountPool(store, data_dir=ROOT / "data")
    aid = args.account or pool.pick()
    api = pool.api(aid)
    cli = pool.client(aid)
    print(f"account={aid} uid={args.uid}", flush=True)

    report: dict = {"account": aid, "uid": args.uid}

    # ---- 1) 修好之后的 search_videos 是否拒绝越界页 ----
    print("--- search_videos 越界行为（修复后）---", flush=True)
    search_rows = []
    for page in (1, 34, 40):
        try:
            r = api.search("原神", page=page, page_size=30)
            row = {"page": page, "ok": True, "api_page": r.get("api_page"),
                   "count": r.get("count"), "total_pages": r.get("total_pages")}
        except Exception as exc:  # noqa: BLE001
            row = {"page": page, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
        search_rows.append(row)
        print(f"  page={page:<4} -> {json.dumps(row, ensure_ascii=False)}", flush=True)
        time.sleep(0.8)
    report["search_videos"] = search_rows

    # ---- 2) 作者投稿列表的越界行为 ----
    print("--- arc/search 越界行为（pn）---", flush=True)
    rows = []
    base = arc_search(cli, args.uid, 1)
    print(f"  pn=1 -> {json.dumps(base, ensure_ascii=False)}", flush=True)
    rows.append(base)
    count = base.get("count") or 0
    pages = max(1, (int(count) + 29) // 30) if count else 1
    for pn in sorted({pages, pages + 1, pages + 50}):
        r = arc_search(cli, args.uid, pn)
        rows.append(r)
        print(f"  pn={pn}（总页数≈{pages}）-> {json.dumps(r, ensure_ascii=False)}", flush=True)
        time.sleep(0.8)
    report["arc_search"] = {"total_pages": pages, "rows": rows}

    same = [r for r in rows if not r.get("soft_risk")]
    mismatch = [r for r in same if r.get("same_page") is False]
    print("\n== 结论 ==")
    print(f"  arc/search 越界回退: {'是' if mismatch else '否'} "
          f"（{[(r['pn'], r.get('api_pn')) for r in mismatch]}）")

    (OUT / f"bound2_{int(time.time())}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

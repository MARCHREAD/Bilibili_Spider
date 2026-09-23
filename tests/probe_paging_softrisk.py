"""深分页软风控探针：page 变大时服务端到底回什么形态。

只用已登录账号发**只读 GET**。逐页记录：
  * 顶层 data 的键、是否出现 v_voucher（顶层/嵌套）
  * 业务主体长度（result / replies）
  * 分页元信息（numResults / numPages / cursor.all_count / cursor.is_end）
  * 是否被**现有**检测逻辑（data 单键 v_voucher）识别出来

用法：python tests/probe_paging_softrisk.py [--account 1] [--kind search|comments|both]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb.accounts import AccountPool
from biliwb.store import Store

OUT = ROOT / "tests" / "_paging"
OUT.mkdir(exist_ok=True)

KEYWORD = "原神"
VIDEO = "BV1X9eb6tEvy"


def find_voucher(obj, path="$", depth=0):
    """递归找出所有 v_voucher 出现位置。"""
    hits = []
    if depth > 3:
        return hits
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "v_voucher":
                hits.append(f"{path}.{k}={str(v)[:24]}")
            hits.extend(find_voucher(v, f"{path}.{k}", depth + 1))
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):
            hits.extend(find_voucher(v, f"{path}[{i}]", depth + 1))
    return hits


def classify(data, body) -> dict:
    """data 的形态画像。"""
    d = data if isinstance(data, dict) else {}
    vouchers = find_voucher(body if body is not None else data)
    shapes = {
        "data_keys": sorted(d)[:12],
        "data_key_count": len(d),
    }
    shapes["v_voucher_paths"] = vouchers[:6]
    shapes["new_detector_hit"] = (isinstance(d, dict) and len(d) == 1 and "v_voucher" in d)
    shapes["any_voucher"] = bool(vouchers)
    return shapes


def probe_search(api, pages: list[int]) -> list[dict]:
    rows = []
    for p in pages:
        t0 = time.time()
        rec = {"page": p}
        try:
            body = api.client.request_json(
                "https://api.bilibili.com/x/web-interface/wbi/search/type",
                params={"search_type": "video", "keyword": KEYWORD, "order": "totalrank",
                        "page": p, "page_size": 30, "duration": 0, "from_source": "",
                        "web_location": 1430654},
                wbi=True, soft=True, retries=0,
                headers={"Referer": "https://search.bilibili.com/"})
        except Exception as exc:  # noqa: BLE001
            rec.update({"error": f"{type(exc).__name__}: {exc}", "seconds": round(time.time() - t0, 1)})
            rows.append(rec)
            print(json.dumps(rec, ensure_ascii=False), flush=True)
            continue
        data = (body or {}).get("data")
        d = data if isinstance(data, dict) else {}
        res = d.get("result") or []
        rec.update({
            "code": (body or {}).get("code"),
            "seconds": round(time.time() - t0, 1),
            "numResults": d.get("numResults"),
            "numPages": d.get("numPages"),
            "result_len": len(res),
            "first_bvid": (res[0] or {}).get("bvid") if res else None,
            "last_bvid": (res[-1] or {}).get("bvid") if res else None,
        })
        rec.update(classify(data, body))
        rows.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
    return rows


def probe_comments(api, max_pages: int) -> list[dict]:
    """顺序推进游标翻页（接口没有 page 参数，只能逐页走）。"""
    import json as _json

    from biliwb.utils import parse_video_ref
    aid = parse_video_ref(VIDEO).get("aid")
    rows = []
    offset = ""
    for p in range(1, max_pages + 1):
        t0 = time.time()
        rec = {"page": p}
        try:
            body = api.client.request_json(
                "https://api.bilibili.com/x/v2/reply/wbi/main",
                params={"oid": aid, "type": 1, "mode": 3,
                        "pagination_str": _json.dumps({"offset": offset}, ensure_ascii=False),
                        "plat": 1, "seek_rpid": "", "web_location": 1315875},
                wbi=True, soft=True, retries=0,
                headers={"Referer": "https://www.bilibili.com/"})
        except Exception as exc:  # noqa: BLE001
            rec.update({"error": f"{type(exc).__name__}: {exc}", "seconds": round(time.time() - t0, 1)})
            rows.append(rec)
            print(json.dumps(rec, ensure_ascii=False), flush=True)
            break
        data = (body or {}).get("data")
        d = data if isinstance(data, dict) else {}
        cursor = d.get("cursor") or {}
        pag = cursor.get("pagination_reply") or {}
        replies = d.get("replies") or []
        nxt = pag.get("next_offset") or ""
        rec.update({
            "code": (body or {}).get("code"),
            "seconds": round(time.time() - t0, 1),
            "replies_len": len(replies),
            "all_count": cursor.get("all_count"),
            "is_end": cursor.get("is_end"),
            "next_offset_nonempty": bool(nxt),
            "next_offset_change": nxt != offset,
        })
        rec.update(classify(data, body))
        rows.append(rec)
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        if not nxt or nxt == offset:
            rec["stopped"] = "游标不再前进"
            break
        offset = nxt
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=int, default=None)
    ap.add_argument("--kind", default="both", choices=("search", "comments", "both"))
    ap.add_argument("--search-pages", default="1,5,10,20,30,40,50")
    ap.add_argument("--comment-pages", type=int, default=25)
    args = ap.parse_args()

    store = Store(ROOT / "data" / "biliwb.db")
    pool = AccountPool(store, data_dir=ROOT / "data")
    aid_acc = args.account or pool.pick()
    acc = store.get_account(aid_acc)
    print(f"account={aid_acc} alias={acc.get('alias')} status={acc.get('last_status')}",
          flush=True)
    api = pool.api(aid_acc)

    report: dict = {"account": aid_acc, "keyword": KEYWORD, "video": VIDEO}
    try:
        if args.kind in ("search", "both"):
            print("--- search 深分页 ---", flush=True)
            pages = [int(x) for x in args.search_pages.split(",")]
            report["search"] = probe_search(api, pages)
        if args.kind in ("comments", "both"):
            print("--- comments 顺序翻页 ---", flush=True)
            report["comments"] = probe_comments(api, args.comment_pages)
    finally:
        (OUT / f"paging_{int(time.time())}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        store.close()

    s = report.get("search") or []
    c = report.get("comments") or []
    print("\n== 汇总 ==")
    print("search 出现 v_voucher 的页:", [r["page"] for r in s if r.get("any_voucher")])
    print("search 空结果页:", [(r["page"], r.get("code")) for r in s if r.get("result_len") == 0])
    print("comments 出现 v_voucher 的页:", [r["page"] for r in c if r.get("any_voucher")])
    print("comments 空页:", [(r["page"], r.get("is_end"), r.get("next_offset_nonempty"))
                             for r in c if r.get("replies_len") == 0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""诊断商品卡片 goods_prefetched_cache 的解析（为什么 ad_signals 为空）。"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402
from biliwb.utils import _goods_ad_signals, extract_comment_links  # noqa: E402

AID = 117162832298619
BV = "BV1Pg8Z62E3C"


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=1.2, retries=2)
    cli.bootstrap()
    cli.warmup()
    cli.gen_ticket()
    cli.wbi_keys(refresh=True)

    data = cli.request_json(C.EP_REPLY_MAIN, params={
        "oid": AID, "type": 1, "mode": 3,
        "pagination_str": json.dumps({"offset": ""}, ensure_ascii=False),
        "plat": 1, "seek_rpid": "", "web_location": 1315875,
    }, wbi=True, headers={"Referer": f"{C.WWW}/video/{BV}/"}) or {}

    top_upper = ((data.get("top") or {}).get("upper")) or {}
    content = top_upper.get("content") or {}
    jump = content.get("jump_url") or {}
    print(f"jump_url 条目数: {len(jump)}", file=sys.stderr)

    for url, meta in jump.items():
        print(f"\n--- {url}", file=sys.stderr)
        print(f"  meta keys: {list(meta.keys()) if isinstance(meta, dict) else type(meta).__name__}",
              file=sys.stderr)
        extra = (meta or {}).get("extra") if isinstance(meta, dict) else None
        print(f"  extra type: {type(extra).__name__}", file=sys.stderr)
        if isinstance(extra, dict):
            print(f"  extra keys: {list(extra.keys())}", file=sys.stderr)
            for k, v in extra.items():
                sval = str(v)
                print(f"    {k}: {type(v).__name__} len={len(sval)} {sval[:160]}", file=sys.stderr)
            cache = extra.get("goods_prefetched_cache")
            print(f"\n  --- 解析 goods_prefetched_cache (type={type(cache).__name__}) ---",
                  file=sys.stderr)
            if cache is None:
                print("    字段不存在！", file=sys.stderr)
            else:
                try:
                    parsed = json.loads(cache) if isinstance(cache, str) else cache
                    print(f"    json.loads OK, keys={list(parsed.keys())}", file=sys.stderr)
                    print(f"    is_ad_loc={parsed.get('is_ad_loc')} "
                          f"resource_id={parsed.get('resource_id')} "
                          f"source_id={parsed.get('source_id')}", file=sys.stderr)
                    ad = parsed.get("ad_content") or {}
                    print(f"    ad_content.creative_id={ad.get('creative_id')} "
                          f"creative_type={ad.get('creative_type')}", file=sys.stderr)
                except Exception as exc:
                    print(f"    json.loads 失败: {type(exc).__name__}: {exc}", file=sys.stderr)
                print(f"    _goods_ad_signals 返回: {_goods_ad_signals(cache)}", file=sys.stderr)

    print("\n--- extract_comment_links 结果 ---", file=sys.stderr)
    print(json.dumps(extract_comment_links(content), ensure_ascii=False, indent=2)[:1200],
          file=sys.stderr)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

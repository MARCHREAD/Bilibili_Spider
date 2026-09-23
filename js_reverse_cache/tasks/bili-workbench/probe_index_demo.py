"""演示持久化 midHash 字典的效果（live）。

第一轮：只用「当前视频评论区」建池碰撞，命中的写入字典。
第二轮：**不再建池**（pool_pages=0，只剩 UP 主），只看字典能认出多少。

第二轮里 index_hits > 0 就说明字典真的跨视频复用了 ——
因为那些用户在第二轮的候选池里并不存在。
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb.api import danmaku as dm  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402
from biliwb.store import MidHashIndex, Store  # noqa: E402

KEYWORD = "原神"
N = 4


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    db = here / "fixtures" / "probe_index_demo.db"
    if db.exists():
        db.unlink()

    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=1.0, jitter=0.3, retries=3)
    store = Store(db)
    cli.midhash_index = MidHashIndex(store)
    cli.bootstrap()
    cli.warmup()
    cli.gen_ticket()
    cli.wbi_keys(refresh=True)

    search = cli.request_json(C.EP_SEARCH_TYPE, params={
        "search_type": "video", "keyword": KEYWORD, "order": "dm", "page": 1,
        "page_size": 30, "duration": 0, "from_source": "", "web_location": 1430654,
    }, wbi=True, headers={"Referer": "https://search.bilibili.com/"})
    bvids = [it.get("bvid") for it in (search or {}).get("result") or [] if it.get("bvid")][:N]
    print(f"样本 {len(bvids)}: {bvids}\n", file=sys.stderr)

    print("=== 第一轮：pool_pages=3（建池碰撞，命中写入字典）===", file=sys.stderr)
    round1 = []
    for bvid in bvids:
        r = dm.video_danmaku(cli, bvid, all_segments=True, max_segments=3,
                             resolve_senders=True, pool_pages=3, enrich_limit=0)
        idn = r["identity"]
        round1.append((bvid, r["count"], idn.get("candidate_pool"), idn.get("resolved"),
                       idn.get("index_hits"), idn.get("pool_hits")))
        print(f"  {bvid}: 弹幕{r['count']:>5} 池{idn.get('candidate_pool'):>3} "
              f"-> resolved={idn.get('resolved')} (index={idn.get('index_hits')}, "
              f"pool={idn.get('pool_hits')})", file=sys.stderr)
    print(f"  字典条目: {store.stats()['midhash_index']}", file=sys.stderr)

    print("\n=== 第二轮：pool_pages=0（不建池，只靠字典）===", file=sys.stderr)
    round2 = []
    for bvid in bvids:
        r = dm.video_danmaku(cli, bvid, all_segments=True, max_segments=3,
                             resolve_senders=True, pool_pages=0, enrich_limit=0)
        idn = r["identity"]
        round2.append((bvid, r["count"], idn.get("candidate_pool"), idn.get("resolved"),
                       idn.get("index_hits"), idn.get("pool_hits")))
        print(f"  {bvid}: 弹幕{r['count']:>5} 池{idn.get('candidate_pool'):>3} "
              f"-> resolved={idn.get('resolved')} (index={idn.get('index_hits')}, "
              f"pool={idn.get('pool_hits')})", file=sys.stderr)

    gain = sum(x[4] or 0 for x in round2)
    print(f"\n  第二轮靠字典认出 {gain} 条弹幕"
          f"（这些用户在第二轮候选池里并不存在）", file=sys.stderr)

    print("\n=== 字典样例（命中次数最高）===", file=sys.stderr)
    for row in store.midhash_top(8):
        print(f"  midHash={row['mid_hash']} uid={row['uid']} "
              f"uname={row['uname']} hits={row['hits']} src={row['source']}", file=sys.stderr)

    store.close()
    if db.exists():
        db.unlink()
    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    print(json.dumps({"round1": round1, "round2": round2},
                     ensure_ascii=False, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

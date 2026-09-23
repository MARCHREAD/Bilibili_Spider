"""演示"候选池越大，uid 还原命中越多"（live）。

对照：
  池 = 只有当前视频评论区（默认）
  池 = 多个视频累积（评论者 + UP 主）

同一批弹幕，用两个池分别碰撞，比较命中数。
最后对命中的 uid 演示 enrich_limit 如何补昵称/等级。
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb.api import danmaku as dm  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402
from biliwb.utils import normalize_mid  # noqa: E402

KEYWORD = "原神"
N_VIDEOS = 5


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=1.0, jitter=0.3, retries=3)
    cli.bootstrap()
    cli.warmup()
    cli.gen_ticket()
    cli.wbi_keys(refresh=True)

    search = cli.request_json(C.EP_SEARCH_TYPE, params={
        "search_type": "video", "keyword": KEYWORD, "order": "dm", "page": 1,
        "page_size": 30, "duration": 0, "from_source": "", "web_location": 1430654,
    }, wbi=True, headers={"Referer": "https://search.bilibili.com/"})
    bvids = [it.get("bvid") for it in (search or {}).get("result") or []
             if it.get("bvid")][:N_VIDEOS]
    print(f"样本视频 {len(bvids)}: {bvids}", file=sys.stderr)

    # 逐个视频：拉弹幕 + 用「只有本视频评论」的池还原
    per_video = []
    for bvid in bvids:
        r = dm.video_danmaku(cli, bvid, all_segments=True, max_segments=3,
                             resolve_senders=True, enrich_limit=0, pool_pages=3)
        per_video.append(r)
        print(f"  {bvid}: 弹幕 {r['count']:>4}  单视频池 {r['identity']['candidate_pool']:>3} uid "
              f"-> 命中 {r['identity']['resolved']}", file=sys.stderr)

    # 累积池：所有视频的候选池并集（这正是批量采集时的自然状态）
    wide: set[int] = set()
    for bvid in bvids:
        r = dm.video_danmaku(cli, bvid, all_segments=True, max_segments=3,
                             resolve_senders=True, enrich_limit=0, pool_pages=8)
        pool = [it["uid"] for it in r["items"] if it["uid"]]
        wide.update(pool)
        # 用累积池重算该视频（用上一次的候选池来源重建）
        print(f"  {bvid}: 弹幕 {r['count']:>4}  深池 {r['identity']['candidate_pool']:>3} uid "
              f"-> 命中 {r['identity']['resolved']}", file=sys.stderr)

    # 用「显式传入的累积池」对每个视频再还原一次，看能否提高命中
    print("\n=== 用累积候选池（跨视频并集）重新还原 ===", file=sys.stderr)
    if wide:
        wide_list = sorted(wide)
        total_before = total_after = 0
        for bvid in bvids:
            r = dm.video_danmaku(cli, bvid, all_segments=True, max_segments=3,
                                 resolve_senders=True, candidate_mids=wide_list,
                                 enrich_limit=0)
            total_after += r["identity"]["resolved"]
            print(f"  {bvid}: 池 {r['identity']['candidate_pool']} uid "
                  f"-> 命中 {r['identity']['resolved']} / {r['count']}", file=sys.stderr)
        print(f"  累积池大小 {len(wide_list)}，跨视频总命中 {total_after}", file=sys.stderr)
    else:
        print("  累积池为空（单视频碰撞全未命中）", file=sys.stderr)

    # enrich 演示：拿一个有命中的视频补昵称/等级
    print("\n=== enrich_limit 演示（补昵称与等级）===", file=sys.stderr)
    target = None
    for bvid in bvids:
        r = dm.video_danmaku(cli, bvid, all_segments=True, max_segments=3,
                             resolve_senders=True, pool_pages=8,
                             enrich_limit=3)
        if r["identity"]["resolved"]:
            target = r
            break
    if target:
        enriched = target["identity"].get("enriched") or {}
        print(f"  视频 {target['bvid']}: 还原 {target['identity']['resolved']} 条，"
              f"发起 {enriched.get('requested')} 次 acc/info", file=sys.stderr)
        for uid, prof in (enriched.get("profiles") or {}).items():
            print(f"    uid={uid} -> {prof.get('uname')} (lv{prof.get('level')}) "
                  f"{str(prof.get('sign'))[:30]}", file=sys.stderr)
        for it in target["items"]:
            if it.get("uname"):
                print(f"    弹幕: [{it['video_time']}] {it['content'][:20]:<22} "
                      f"<- {it['uname']} (uid={it['uid']}, lv{it['level']})", file=sys.stderr)
    else:
        print("  这些视频样本中没有可 enrich 的命中（属正常：候选池与弹幕发送者无重叠）",
              file=sys.stderr)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    print(json.dumps({
        "per_video_single_pool": [
            {"bvid": r["bvid"], "danmaku": r["count"],
             "pool": r["identity"]["candidate_pool"],
             "resolved": r["identity"]["resolved"]} for r in per_video],
        "wide_pool_size": len(wide),
    }, ensure_ascii=False, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

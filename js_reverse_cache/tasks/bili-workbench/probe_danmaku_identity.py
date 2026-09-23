"""演示弹幕发送者身份还原的三档效果（live）。

A. 不还原            -> 每条弹幕只有 midHash
B. 还原 uid          -> 用候选池碰撞，能对上的回填 uid
C. 还原 uid + 补资料 -> 再对命中的 uid 调 acc/info，拿昵称与等级
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb.api import danmaku as dm  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402

BV = "BV1BHez6cEEm"


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=1.1, retries=2)
    cli.bootstrap()
    cli.warmup()
    cli.gen_ticket()
    cli.wbi_keys(refresh=True)

    print("=== A. resolve_senders=False（默认）===", file=sys.stderr)
    a = dm.video_danmaku(cli, BV, all_segments=True, resolve_senders=False)
    print(f"  弹幕 {a['count']} 条，identity.supported={a['identity']['supported']}", file=sys.stderr)
    for it in a["items"][:3]:
        print(f"    {it['video_time']}  {it['content'][:22]:<24} "
              f"midHash={it['mid_hash']}  uid={it['uid']}  uname={it['uname']}", file=sys.stderr)

    print("\n=== B. resolve_senders=True, enrich_limit=0（只还原 uid）===", file=sys.stderr)
    b = dm.video_danmaku(cli, BV, all_segments=True, resolve_senders=True, enrich_limit=0)
    idb = b["identity"]
    print(f"  候选池 {idb['candidate_pool']} 个 uid（来源: {idb.get('pool_source')}）", file=sys.stderr)
    print(f"  还原成功 {idb['resolved']} / 未还原 {idb['unresolved']}"
          f"  （共 {b['count']} 条弹幕）", file=sys.stderr)
    hit = [it for it in b["items"] if it["uid"]]
    for it in hit[:5]:
        print(f"    {it['video_time']}  {it['content'][:22]:<24} midHash={it['mid_hash']} "
              f"-> uid={it['uid']}  uname={it['uname']}", file=sys.stderr)
    print(f"  合计命中 {len(hit)} 条，去重后 {len({it['uid'] for it in hit})} 个 uid", file=sys.stderr)

    print("\n=== C. resolve_senders=True, enrich_limit=3（再补前 3 个 uid 的资料）===",
          file=sys.stderr)
    c = dm.video_danmaku(cli, BV, all_segments=True, resolve_senders=True, enrich_limit=3)
    enriched = c["identity"].get("enriched") or {}
    print(f"  发起 {enriched.get('requested')} 次 acc/info 请求", file=sys.stderr)
    for uid, prof in (enriched.get("profiles") or {}).items():
        print(f"    uid={uid} -> uname={prof.get('uname')} level={prof.get('level')} "
              f"sign={str(prof.get('sign'))[:24]}", file=sys.stderr)
    for it in c["items"]:
        if it.get("uname"):
            print(f"    弹幕已带上身份: {it['video_time']} {it['content'][:18]:<20} "
                  f"uid={it['uid']} uname={it['uname']} lv={it['level']}", file=sys.stderr)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    print("\n=== 汇总 ===", file=sys.stderr)
    print(json.dumps({
        "A_无还原": {"count": a["count"], "identity_supported": a["identity"]["supported"]},
        "B_只还原uid": {"pool": idb["candidate_pool"], "resolved": idb["resolved"],
                        "unresolved": idb["unresolved"]},
        "C_含资料": {"enrich_requests": enriched.get("requested")},
    }, ensure_ascii=False, indent=2), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

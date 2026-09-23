"""深挖置顶评论：data.top 的真实结构 + 用 rpid 取回完整内容 + mid 类型检查。"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402

AID = 117162832298619
BV = "BV1Pg8Z62E3C"
UP_MID = 542316830


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

    top = data.get("top") or {}
    print("=== data.top 完整内容 ===", file=sys.stderr)
    print(json.dumps(top, ensure_ascii=False)[:3000], file=sys.stderr)

    print("\n=== data.top.upper 里有什么 ===", file=sys.stderr)
    tu = top.get("upper")
    if isinstance(tu, dict):
        print(f"  keys={list(tu.keys())}", file=sys.stderr)
        print(f"  rpid={tu.get('rpid')} member={(tu.get('member') or {}).get('uname')}",
              file=sys.stderr)
        c = tu.get("content") or {}
        print(f"  content keys={list(c.keys())}", file=sys.stderr)
        print(f"  message={str(c.get('message'))[:200]}", file=sys.stderr)
        if c.get("jump_url"):
            print(f"  jump_url={json.dumps(c['jump_url'], ensure_ascii=False)[:800]}", file=sys.stderr)
    else:
        print(f"  type={type(tu).__name__} value={str(tu)[:200]}", file=sys.stderr)

    print("\n=== data.top_replies 完整内容 ===", file=sys.stderr)
    print(json.dumps(data.get("top_replies"), ensure_ascii=False)[:1500], file=sys.stderr)

    # mid 类型检查（关键：字符串 vs 整数会让作者判定永远为 False）
    print("\n=== mid 类型检查 ===", file=sys.stderr)
    for i, r in enumerate((data.get("replies") or [])[:3]):
        m = (r.get("member") or {}).get("mid")
        print(f"  replies[{i}].member.mid = {m!r} type={type(m).__name__} "
              f"== {UP_MID} -> {m == UP_MID}", file=sys.stderr)
    if isinstance(tu, dict):
        m = (tu.get("member") or {}).get("mid")
        print(f"  top.upper.member.mid = {m!r} type={type(m).__name__} "
              f"== {UP_MID} -> {m == UP_MID}", file=sys.stderr)

    # 用置顶 rpid 直接取回完整评论
    rpids = [it.get("rpid") for it in (data.get("top_replies") or []) if it.get("rpid")]
    if isinstance(tu, dict) and tu.get("rpid"):
        rpids.append(tu["rpid"])
    print(f"\n=== 用 seek_rpid 取回置顶评论 {rpids} ===", file=sys.stderr)
    for rpid in rpids[:3]:
        try:
            got = cli.request_json(C.EP_REPLY_MAIN, params={
                "oid": AID, "type": 1, "mode": 3,
                "pagination_str": json.dumps({"offset": ""}, ensure_ascii=False),
                "plat": 1, "seek_rpid": rpid, "web_location": 1315875,
            }, wbi=True, headers={"Referer": f"{C.WWW}/video/{BV}/"}) or {}
            found = None
            for r in (got.get("replies") or []):
                if r.get("rpid") == rpid:
                    found = r
                    break
            if found:
                c = found.get("content") or {}
                print(f"  rpid={rpid} 命中 replies: uname={(found.get('member') or {}).get('uname')} "
                      f"mid={(found.get('member') or {}).get('mid')!r}", file=sys.stderr)
                print(f"    message={str(c.get('message'))[:160]}", file=sys.stderr)
                print(f"    jump_url={json.dumps(c.get('jump_url'), ensure_ascii=False)[:900]}",
                      file=sys.stderr)
            else:
                print(f"  rpid={rpid} 未在 replies 中找到 "
                      f"(replies={len(got.get('replies') or [])}, "
                      f"top_replies={len(got.get('top_replies') or [])})", file=sys.stderr)
        except Exception as exc:
            print(f"  rpid={rpid} 请求失败: {exc}", file=sys.stderr)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""诊断 BV1Pg8Z62E3C 的置顶评论与富文本(商品卡片)结构。

要回答两个问题：
  1. 为什么 fetch_pinned_comment 返回 None —— 置顶评论到底在哪个字段？
  2. 带货链接在数据层长什么样（jump_url / goods / HTML）？
"""

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


def fetch(cli, mode, offset=""):
    return cli.request_json(C.EP_REPLY_MAIN, params={
        "oid": AID, "type": 1, "mode": mode,
        "pagination_str": json.dumps({"offset": offset}, ensure_ascii=False),
        "plat": 1, "seek_rpid": "", "web_location": 1315875,
    }, wbi=True, headers={"Referer": f"{C.WWW}/video/{BV}/"})


def main() -> int:
    here = pathlib.Path(__file__).resolve().parent
    cli = BiliClient(cookie_file=str(here / "session.txt"), min_delay=1.2, retries=2)
    cli.bootstrap()
    cli.warmup()
    cli.gen_ticket()
    cli.wbi_keys(refresh=True)

    for mode in (3, 2):
        data = fetch(cli, mode) or {}
        print(f"\n{'='*70}\n=== mode={mode} 顶层 keys: {list(data.keys())}", file=sys.stderr)

        # 1) 置顶候选字段全景
        for key in ("top", "top_replies", "upper", "note", "control"):
            val = data.get(key)
            if isinstance(val, dict):
                print(f"  {key}: dict keys={list(val.keys())}", file=sys.stderr)
                if val.get("rpid"):
                    print(f"    -> 有 rpid={val.get('rpid')}", file=sys.stderr)
            elif isinstance(val, list):
                print(f"  {key}: list len={len(val)}", file=sys.stderr)
                for i, it in enumerate(val[:3]):
                    if isinstance(it, dict):
                        print(f"    [{i}] keys={list(it.keys())[:12]} rpid={it.get('rpid')}",
                              file=sys.stderr)
            else:
                print(f"  {key}: {str(val)[:80]}", file=sys.stderr)

        upper = data.get("upper") or {}
        if isinstance(upper, dict):
            print(f"  upper 全文: {json.dumps(upper, ensure_ascii=False)[:600]}", file=sys.stderr)

        # 2) 前几条评论的 content 完整结构（找 jump_url / goods）
        for i, r in enumerate((data.get("replies") or [])[:4]):
            content = r.get("content") or {}
            print(f"\n  --- replies[{i}] rpid={r.get('rpid')} mid={(r.get('member') or {}).get('mid')} "
                  f"is_up={(r.get('member') or {}).get('mid') == UP_MID}", file=sys.stderr)
            print(f"      content keys: {list(content.keys())}", file=sys.stderr)
            print(f"      message: {str(content.get('message'))[:200]}", file=sys.stderr)
            if content.get("jump_url"):
                print(f"      jump_url: {json.dumps(content['jump_url'], ensure_ascii=False)[:600]}",
                      file=sys.stderr)
            for extra in ("goods", "goods_info", "card", "rich_text", "emote"):
                if content.get(extra):
                    print(f"      {extra}: {json.dumps(content[extra], ensure_ascii=False)[:300]}",
                          file=sys.stderr)
            # 顶层其它可能载货字段
            for k, v in r.items():
                if k in ("content", "member", "replies"):
                    continue
                if isinstance(v, (dict, list)) and v:
                    txt = json.dumps(v, ensure_ascii=False)
                    if any(s in txt for s in ("goods", "mall", "b23.tv", "购买", "商品")):
                        print(f"      顶层 {k}: {txt[:400]}", file=sys.stderr)

        # 3) 该视频是否真的存在置顶（用 seek_rpid=0 或不同参数再试）
        if mode == 3:
            alt = cli.request_json(C.EP_REPLY_MAIN, params={
                "oid": AID, "type": 1, "mode": 3, "next": 0, "ps": 20, "plat": 1,
    "web_location": 1315875}, wbi=True, headers={"Referer": f"{C.WWW}/video/{BV}/"})
            print(f"\n  传统分页参数(next/ps) 返回 keys: {list((alt or {}).keys())}", file=sys.stderr)
            print(f"    top={'有' if (alt or {}).get('top') else '无'} "
                  f"upper.top={'有' if ((alt or {}).get('upper') or {}).get('top') else '无'}",
                  file=sys.stderr)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

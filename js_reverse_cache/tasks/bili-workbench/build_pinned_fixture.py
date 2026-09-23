"""生成置顶评论回归 fixture（裁剪后的真实数据）。

来源：BV1Pg8Z62E3C (aid 117162832298619) 的 `x/v2/reply/wbi/main` 响应。
只保留判定需要的字段，去掉头像装饰等大块无关数据。

用法：python js_reverse_cache/tasks/bili-workbench/build_pinned_fixture.py
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

MEMBER_KEEP = ("mid", "uname", "sex", "sign", "level_info", "vip", "official_verify")


def trim_member(member: dict | None) -> dict:
    member = member or {}
    return {k: member.get(k) for k in MEMBER_KEEP if k in member}


def trim_reply(reply: dict) -> dict:
    return {
        "rpid": reply.get("rpid"),
        "oid": reply.get("oid"),
        "mid": reply.get("mid"),
        "root": reply.get("root"),
        "ctime": reply.get("ctime"),
        "like": reply.get("like"),
        "rcount": reply.get("rcount"),
        "member": trim_member(reply.get("member")),
        "content": reply.get("content"),
        "up_action": reply.get("up_action"),
    }


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
    upper = top.get("upper")
    if not isinstance(upper, dict) or not upper.get("rpid"):
        print("!! 未取到 top.upper，无法生成 fixture", file=sys.stderr)
        return 1

    # 同时收一条普通评论作为"非作者"负对照
    plain = None
    for r in (data.get("replies") or []):
        if r.get("rpid") != upper.get("rpid"):
            plain = trim_reply(r)
            break

    fixture = {
        "kind": "pinned-comment-with-goods-card",
        "source": f"GET {C.EP_REPLY_MAIN} oid={AID} (BV={BV})",
        "note": ("真实响应裁剪：只保留判定所需字段。所有内容均为公开评论数据，"
                 "不含 cookie / token。"),
        "structure_facts": {
            "data.top": "容器 {admin, upper, vote}，不是评论对象本身",
            "data.top.upper": "UP 主置顶评论（完整对象）",
            "data.top_replies": "置顶评论的引用/副本列表",
            "member.mid": "字符串（如 '542316830'）",
            "owner.mid": "整数（如 542316830）—— 必须归一化后比较",
            "link_source": "content.jump_url 是链接权威来源，正文可能只有文字",
        },
        "up_mid": 542316830,
        "top_container": {"upper": trim_reply(upper),
                          "admin": top.get("admin"),
                          "vote": top.get("vote")},
        "top_replies": [trim_reply(r) for r in (data.get("top_replies") or [])],
        "plain_reply": plain,
    }

    out = here / "fixtures" / "pinned_comment_goods.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {out}", file=sys.stderr)

    content = (upper.get("content") or {})
    jump = content.get("jump_url") or {}
    print(f"置顶评论 rpid={upper.get('rpid')} mid={upper.get('mid')!r} "
          f"jump_url={list(jump)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

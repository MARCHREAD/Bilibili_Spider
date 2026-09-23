"""2.3 视频评论：主评论游标分页 + 二级评论 + 评论者身份/等级。

分页形状（live 报文实测）
------------------------
`x/v2/reply/wbi/main` **没有** next/ps 传统分页参数，而是：

    ?oid=<aid>&type=1&mode=3&pagination_str={"offset":"<cursor>"}&plat=1&seek_rpid=&web_location=1315875

下一页游标从响应 `cursor.pagination_reply.next_offset` 取。
因此"第 N 页"必须顺序推进，本模块按 (aid, sort) 缓存游标链，避免重复来回。
"""

from __future__ import annotations

import json
from typing import Any

from .. import constants as C
from ..client import BiliClient
from ..utils import extract_comment_links, normalize_mid, ts_to_str
from .paging import MAX_PAGES, clamp_pages, page_detail, paging_meta

SORT_MODE = {"hot": 3, "time": 2}


def _fetch_main(client: BiliClient, aid: int, mode: int, offset: str) -> dict:
    return client.request_json(
        C.EP_REPLY_MAIN,
        params={
            "oid": aid, "type": 1, "mode": mode,
            "pagination_str": json.dumps({"offset": offset}, ensure_ascii=False),
            "plat": 1, "seek_rpid": "", "web_location": 1315875,
        },
        wbi=True,
        headers={"Referer": f"{C.WWW}/"},
    ) or {}


def normalize_member(member: dict | None) -> dict[str, Any]:
    member = member or {}
    return {
        # 必须归一化：接口给的 member.mid 是字符串，view.owner.mid 是整数
        "mid": normalize_mid(member.get("mid")),
        "uname": member.get("uname"),
        "sex": member.get("sex"),
        "sign": member.get("sign"),
        "avatar": member.get("avatar"),
        "level": (member.get("level_info") or {}).get("current_level"),
        "vip_status": (member.get("vip") or {}).get("vipStatus"),
        "is_senior": (member.get("vip") or {}).get("vipType", 0) > 0,
        "user_senior_status": (member.get("user_senior_status") or {}).get("status"),
    }


def normalize_reply(reply: dict) -> dict[str, Any]:
    content = reply.get("content") or {}
    member = normalize_member(reply.get("member"))
    links = extract_comment_links(content)
    return {
        "rpid": reply.get("rpid"),
        "oid": reply.get("oid"),
        "root": reply.get("root"),
        "parent": reply.get("parent"),
        "mid": member.get("mid"),
        "message": content.get("message"),
        "links": links,
        "has_link": bool(links),
        "goods_links": [l for l in links if l.get("kind") == "goods"],
        "ctime": reply.get("ctime"),
        "ctime_str": ts_to_str(reply.get("ctime")),
        "like": reply.get("like"),
        "rcount": reply.get("rcount"),
        "member": member,
        "is_up_top": bool(reply.get("up_action", {}).get("like")) if isinstance(
            reply.get("up_action"), dict) else False,
        "reply_control": reply.get("reply_control"),
    }


def extract_pinned(data: dict) -> dict | None:
    """从 `x/v2/reply/wbi/main` 的响应里挑出置顶评论（纯函数，便于离线回归）。

    实测结构坑（BV1Pg8Z62E3C, rpid 315741109936）：
    `data.top` **不是**评论对象，而是一个容器：

        {"admin": <管理员置顶|null>, "upper": <UP 主置顶|null>, "vote": ...}

    真正的评论体在 `top.upper` / `top.admin`。直接对 `data.top` 取 `rpid`
    会永远拿到空值，从而误判"没有置顶评论"（此前的真实缺陷）。
    `data.top_replies` 是同一批置顶的引用/副本，作为兜底。
    """
    if not isinstance(data, dict):
        return None

    top = data.get("top")
    candidate: dict | None = None
    source: str | None = None

    if isinstance(top, dict):
        for key in ("upper", "admin"):
            node = top.get(key)
            if isinstance(node, dict) and node.get("rpid"):
                candidate, source = node, f"top.{key}"
                break
        if candidate is None and top.get("rpid"):      # 老结构兼容
            candidate, source = top, "top"
    if candidate is None:
        for ref in (data.get("top_replies") or []):
            if isinstance(ref, dict) and ref.get("rpid"):
                candidate, source = ref, "top_replies"
                break
    if candidate is None:
        return None

    out = normalize_reply(candidate)
    out["pinned"] = True
    out["pinned_source"] = source
    return out


def fetch_pinned_comment(client: BiliClient, aid: int) -> dict | None:
    """取置顶评论（含商品卡片链接与作者归属）。"""
    try:
        data = _fetch_main(client, aid, 3, "")
    except Exception:
        return None
    return extract_pinned(data)


def _resolve_next_offset(data: dict) -> str:
    cursor = data.get("cursor") or {}
    pagination = cursor.get("pagination_reply") or {}
    return pagination.get("next_offset") or ""


def _page_at(client: BiliClient, slot: dict, aid: int, mode: int,
             page_no: int) -> dict | None:
    """把游标链推进到第 page_no 页并返回该页 data；None 表示已到末尾。

    游标是按页顺序推进的，所以"跳页"只能一页页走过来；`slot["pages"]` 缓存已取过的页，
    同一次会话里往回翻不会重复请求。
    """
    while len(slot["offsets"]) <= page_no:
        prev_index = len(slot["offsets"]) - 1
        if prev_index not in slot["pages"]:
            slot["pages"][prev_index] = _fetch_main(client, aid, mode,
                                                    slot["offsets"][prev_index])
        nxt = _resolve_next_offset(slot["pages"][prev_index])
        if not nxt:
            break
        slot["offsets"].append(nxt)
    if page_no > len(slot["offsets"]):
        return None
    data = slot["pages"].get(page_no - 1)
    if data is None:
        data = _fetch_main(client, aid, mode, slot["offsets"][page_no - 1])
        slot["pages"][page_no - 1] = data
    return data


def video_comments(
    client: BiliClient,
    ref: str,
    cache: dict,
    page: int = 1,
    page_size: int = 20,
    sort: str = "hot",
    with_sub: bool = True,
    sub_pages: int = 1,
    pages: int = 1,
) -> dict[str, Any]:
    """主评论：`page` 是起始页，`pages` 是从它开始连续抓几页（1..250）。

    接口本身是游标式（没有 page 参数），所以多页 = 顺序推进游标链多次；
    返回里 `items` 是各页合并结果，`per_page` 给出每页的条数与 is_end。
    """
    from ..utils import parse_video_ref

    if sort not in SORT_MODE:
        raise ValueError(f"sort 非法: {sort}，可选 {list(SORT_MODE)}")
    page = max(1, int(page))
    want = clamp_pages(pages)
    sub_pages = max(0, min(int(sub_pages), 5))

    parsed = parse_video_ref(ref)
    bvid = parsed.get("bvid")
    if not bvid:
        raise ValueError("评论需要 BV 号或视频链接")
    aid = parsed.get("aid")
    mode = SORT_MODE[sort]

    slot = cache.setdefault((aid, mode), {"offsets": [""], "pages": {}, "aid": aid})

    items_all: list[dict] = []
    done: list[dict] = []
    first_data: dict | None = None
    last_data: dict | None = None
    last_raw: list = []
    stop: str | None = None
    for i in range(want):
        cur = page + i
        data = _page_at(client, slot, aid, mode, cur)
        if data is None:
            stop = "cursor_end" if i > 0 else "no_next_offset"
            break
        if first_data is None:
            first_data = data
        last_data = data
        raw_replies = data.get("replies") or []
        last_raw = raw_replies
        page_items = [normalize_reply(r) for r in raw_replies[:page_size]]
        if with_sub:
            for item in page_items:
                if item.get("rcount"):
                    item["sub_comments"] = fetch_sub_comments(
                        client, aid, item["rpid"], pages=sub_pages)
        items_all.extend(page_items)
        cursor = data.get("cursor") or {}
        done.append(page_detail(cur, len(page_items),
                                all_count=cursor.get("all_count"),
                                is_end=cursor.get("is_end")))
        if cursor.get("is_end"):
            stop = "cursor_end"
            break
        if not raw_replies:
            stop = "empty_page"
            break

    if first_data is None:
        return {
            "bvid": bvid, "aid": aid, "page": page, "page_size": page_size,
            "sort": sort, "count": 0, "items": [], "cursor": {},
            "hint": "已到评论末页", "max_pages": MAX_PAGES,
        }

    cursor = (last_data or {}).get("cursor") or {}
    out = {
        "bvid": bvid,
        "aid": aid,
        "page": page,
        "page_size": page_size,
        "sort": sort,
        "mode": mode,
        "all_count": cursor.get("all_count"),
        "is_end": cursor.get("is_end"),
        "next_offset": _resolve_next_offset(last_data or {}),
        "count": len(items_all),
        "items": items_all,
        # 置顶评论取第一页（置顶只在首屏有意义）
        "top": normalize_reply(first_data["top"]) if isinstance(first_data.get("top"), dict)
               and (first_data.get("top") or {}).get("rpid") else None,
        "upper_top": normalize_reply((first_data.get("upper") or {}).get("top"))
                     if isinstance((first_data.get("upper") or {}).get("top"), dict)
                     and ((first_data.get("upper") or {}).get("top") or {}).get("rpid") else None,
        "max_pages": MAX_PAGES,
    }
    out.update(paging_meta(want, done, page, stop))
    # 静默截断保护：本页为空，但服务端同时说"还没到底"且总数非零 —— 这个组合自相矛盾，
    # 最可能是分页被风控/降级截断。旧实现会把它当成"没有更多评论"，从而**悄悄少数据**。
    # （软风控本身已由 client 的多轮重试拦住，这里防的是不带 v_voucher 的降级形态。）
    all_count = cursor.get("all_count")
    if not last_raw and cursor.get("is_end") in (0, False) and (all_count or 0) > 0:
        out["suspicious_empty_page"] = True
        out["hint"] = (f"本页为空但服务端称未到底（is_end={cursor.get('is_end')}, "
                       f"all_count={all_count}）：疑似被截断，建议重试本页")
    return out


def fetch_sub_comments(client: BiliClient, aid: int, root: int, pages: int = 1) -> list[dict]:
    """二级评论（楼中楼）：传统 pn/ps 分页。"""
    out: list[dict] = []
    for pn in range(1, max(1, pages) + 1):
        try:
            data = client.request_json(
                C.EP_REPLY_SUB,
                params={"oid": aid, "type": 1, "root": root, "ps": 20, "pn": pn,
                        "web_location": 333.788},
                headers={"Referer": f"{C.WWW}/"},
                retries=1,
            ) or {}
        except Exception:
            break
        batch = data.get("replies") or []
        if not batch:
            break
        for reply in batch:
            item = normalize_reply(reply)
            item["is_sub"] = True
            item["parent_str"] = (reply.get("content") or {}).get("message")
            out.append(item)
        page_info = data.get("page") or {}
        if pn >= int(page_info.get("count", 1) or 1):
            break
    return out

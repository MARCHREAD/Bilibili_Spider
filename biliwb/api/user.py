"""2.5 用户资料 与 2.6 作者视频列表。

字段来源（live 取证）
---------------------
* `space/wbi/acc/info`  (wbi + gaia 槽位) -> 昵称/简介/等级/性别/头像/官方认证
* `relation/stat`                          -> 关注数、粉丝数
* `space/upstat`                           -> 播放数、获赞数（**需登录**，未登录返回 {}）
* `space/navnum`                           -> 视频数、专栏数、相册数等
* `space/setting`                          -> privacy 隐私位（判断关注/粉丝列表是否可见）
* `relation/followings` / `relation/followers` -> 名单（需登录且对方未设隐私）
* `ugcpay-space/stat`                      -> 充电人数
* `polymer/web-dynamic/v1/feed/space`      -> 动态总数 total
"""

from __future__ import annotations

from typing import Any

from .. import constants as C
from ..client import BiliClient, gaia_slots
from .paging import MAX_PAGES, clamp_pages, page_detail, paging_meta


def _try(fn, errors: dict, key: str):
    try:
        return fn()
    except Exception as exc:
        errors[key] = f"{type(exc).__name__}: {exc}"
        return None


def resolve_mid(client: BiliClient, ref: str) -> int:
    """uid / 空间链接 / 准确用户名 -> uid。"""
    from ..utils import parse_space_ref
    from .search import resolve_username

    parsed = parse_space_ref(ref)
    if parsed.get("mid"):
        return int(parsed["mid"])
    return resolve_username(client, parsed["username"])


def user_profile(
    client: BiliClient,
    ref: str,
    with_followings: bool = False,
    with_followers: bool = False,
    list_pages: int = 1,
    list_page_size: int = 50,
    with_dynamic_scan: bool = False,
    dynamic_scan_batches: int = 50,
) -> dict[str, Any]:
    mid = resolve_mid(client, ref)
    errors: dict[str, str] = {}
    # 名单/动态扫描的页数同样受 250 上限约束
    list_pages = clamp_pages(list_pages)
    dynamic_scan_batches = clamp_pages(dynamic_scan_batches)

    info = _try(lambda: client.request_json(
        C.EP_ACC_INFO,
        params={"mid": mid, "token": "", "platform": "web",
                "web_location": 1550101, **gaia_slots()},
        wbi=True,
    ), errors, "acc_info")

    relation = _try(lambda: client.request_json(
        C.EP_RELATION_STAT, params={"vmid": mid, "web_location": 333.1387}
    ), errors, "relation_stat")

    upstat = _try(lambda: client.request_json(
        C.EP_UPSTAT, params={"mid": mid, "web_location": 333.1387}
    ), errors, "upstat")

    navnum = _try(lambda: client.request_json(
        C.EP_NAVNUM, params={"mid": mid, "web_location": 333.1387}
    ), errors, "navnum")

    setting = _try(lambda: client.request_json(
        C.EP_SETTING, params={"mid": mid, "web_location": 333.1387}
    ), errors, "setting")

    dyn_total = _try(lambda: (client.request_json(
        C.EP_DYN_SPACE, params={"host_mid": mid, "web_location": 333.1387}
    ) or {}).get("total"), errors, "dynamic_total")

    # feed/space 的 total 实测不可靠（有 12 条 items 却返回 "0"），
    # 需要准确值时用翻页累计。
    dynamic_count = _as_int(dyn_total)
    dynamic_method = "feed_total"
    if with_dynamic_scan:
        scanned = _scan_dynamic_count(client, mid, dynamic_scan_batches)
        if scanned is not None:
            dynamic_count = scanned
            dynamic_method = "paged_scan"

    privacy = ((setting or {}).get("privacy") or {})
    following_hidden = privacy.get("disable_following") == 1
    fans_hidden = privacy.get("disable_show_fans") == 1

    # 充电人数在 acc/info.elec.show_info.total（实测 930 / 1139），
    # 不需要单独接口：x/ugcpay-space/stat 已 404，x/ugcpay-rank 被 -352 风控。
    elec_info = ((info or {}).get("elec") or {}).get("show_info") or {}
    charging = elec_info.get("total")

    out: dict[str, Any] = {
        "input": ref,
        "uid": mid,
        "name": (info or {}).get("name"),
        "sign": (info or {}).get("sign"),
        "face": (info or {}).get("face"),
        "sex": (info or {}).get("sex"),
        "level": (info or {}).get("level"),
        "birthday": (info or {}).get("birthday"),
        "official": ((info or {}).get("official") or {}).get("title"),
        "vip": ((info or {}).get("vip") or {}).get("label", {}).get("text")
               if isinstance((info or {}).get("vip"), dict) else None,
        "following": (relation or {}).get("following"),
        "follower": (relation or {}).get("follower"),
        "likes": (upstat or {}).get("likes"),
        "play": ((upstat or {}).get("archive") or {}).get("view"),
        "video_count": (navnum or {}).get("video"),
        "article_count": (navnum or {}).get("article"),
        "album_count": (navnum or {}).get("album"),
        "season_count": (navnum or {}).get("season_num"),
        "opus_count": (navnum or {}).get("opus"),
        "dynamic_count": dynamic_count,
        "dynamic_count_method": dynamic_method,
        "charging_count": charging,
        "charging": {
            "state": elec_info.get("state"),
            "title": elec_info.get("title"),
            "jump_url": elec_info.get("jump_url"),
            "top": [
                {"pay_mid": it.get("pay_mid"), "rank": it.get("rank"),
                 "uname": it.get("uname"), "message": it.get("message")}
                for it in (elec_info.get("list") or [])[:10]
            ],
        },
        "privacy": {
            "following_hidden": following_hidden,
            "fans_hidden": fans_hidden,
            "raw": privacy,
        },
        "errors": errors,
    }

    if with_followings:
        out["followings"] = fetch_relation_list(
            client, C.EP_FOLLOWINGS, mid, list_pages, list_page_size,
            hidden=following_hidden, kind="关注")
    if with_followers:
        out["followers"] = fetch_relation_list(
            client, C.EP_FOLLOWERS, mid, list_pages, list_page_size,
            hidden=fans_hidden, kind="粉丝")

    if not upstat:
        out["hint_upstat"] = "播放数/获赞数需要登录态，未登录时 upstat 返回空对象。"
    return out


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _scan_dynamic_count(client: BiliClient, mid: int, max_batches: int) -> int | None:
    """翻页累计动态条数（feed/space 的 total 不可靠时的准确来源）。"""
    seen, offset, batches = 0, "", 0
    while batches < max(1, max_batches):
        params = {"host_mid": mid, "web_location": 333.1387, "timezone_offset": -480}
        if offset:
            params["offset"] = offset
        try:
            data = client.request_json(C.EP_DYN_SPACE, params=params) or {}
        except Exception:
            return seen or None
        seen += len(data.get("items") or [])
        batches += 1
        offset = data.get("offset") or ""
        if not data.get("has_more") or not offset:
            break
    return seen


def fetch_relation_list(client: BiliClient, endpoint: str, mid: int, pages: int,
                        page_size: int, hidden: bool, kind: str) -> dict[str, Any]:
    """拉关注/粉丝名单；隐私受限时明确返回原因而不是空列表。"""
    if hidden:
        return {
            "available": False,
            "reason": f"对方已设置隐私，{kind}列表不可见（space/setting 的 privacy 位为 1）",
            "items": [],
        }
    items: list[dict] = []
    total = None
    error = None
    for page in range(1, max(1, pages) + 1):
        try:
            data = client.request_json(
                endpoint,
                params={"vmid": mid, "pn": page, "ps": min(page_size, 50),
                        "order": "desc", "order_type": "attention",
                        "web_location": 333.1387},
            ) or {}
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            break
        batch = data.get("list") or []
        total = data.get("total", total)
        for entry in batch:
            items.append({
                "mid": entry.get("mid"),
                "uname": entry.get("uname"),
                "sign": entry.get("sign"),
                "face": entry.get("face"),
                "vip": ((entry.get("vip") or {}).get("vipType", 0) > 0),
                "official": ((entry.get("official_verify") or {}).get("desc")),
                "special": entry.get("special"),
            })
        if len(batch) < page_size:
            break
    return {
        "available": error is None,
        "error": error,
        "total": total,
        "count": len(items),
        "items": items,
        "reason": None if items else (
            error or f"接口未返回{kind}列表（多数情况需要登录态，或对方隐私受限）"),
    }


def user_videos(
    client: BiliClient,
    ref: str,
    page: int = 1,
    page_size: int = 30,
    order: str = "pubdate",
    keyword: str = "",
    tid: int = 0,
    pages: int = 1,
) -> dict[str, Any]:
    """2.6 作者投稿列表（分页）。

    `page` 是起始页，`pages` 是从它开始连续抓几页（1..250）。
    """
    if order not in ("pubdate", "click", "stow"):
        raise ValueError(f"order 非法: {order}，可选 pubdate / click / stow")
    mid = resolve_mid(client, ref)
    page = max(1, int(page))
    want = clamp_pages(pages)
    page_size = max(1, min(int(page_size), 50))

    items_all: list[dict] = []
    done: list[dict] = []
    meta: dict = {}
    page_info: dict = {}
    stop: str | None = None
    for i in range(want):
        cur = page + i
        data = client.request_json(
            C.EP_ARC_SEARCH,
            params={
                "mid": mid, "pn": cur, "ps": page_size, "tid": tid,
                "special_type": "", "order": order, "index": 0, "keyword": keyword,
                "order_avoided": "true", "platform": "web", "web_location": 333.1387,
                **gaia_slots(),
            },
            wbi=True,
            headers={"Referer": f"https://space.bilibili.com/{mid}/upload/video"},
        ) or {}
        vlist = ((data.get("list") or {}).get("vlist")) or []
        page_items = [{
            "bvid": v.get("bvid"),
            "aid": v.get("aid"),
            "title": v.get("title"),
            "description": v.get("description"),
            "created": v.get("created"),
            "length": v.get("length"),
            "play": v.get("play"),
            "video_review": v.get("video_review"),
            "comment": v.get("comment"),
            "favorites": v.get("favorites"),
            "pic": v.get("pic"),
            "is_union_video": v.get("is_union_video"),
            "is_pay": v.get("is_pay"),
        } for v in vlist]
        items_all.extend(page_items)
        done.append(page_detail(cur, len(page_items)))
        meta = data
        page_info = data.get("page") or {}
        # 越界语义（实测，见 tests/probe_user_videos_bound.py）：arc/search 的 pn 超出总页数时
        # 返回**空列表**且 api 的 pn 保持不变（不像搜索接口那样回退到别的页），
        # 所以"空列表"可以直接当作"已到末页"。
        if not page_items:
            stop = "no_more"
            break

    total = page_info.get("count")
    if items_all:
        hint = None
    elif page > 1 and total:
        hint = f"已到投稿末页（共 {total} 条 ≈ {max(1, (int(total) + page_size - 1) // page_size)} 页）"
    else:
        hint = "接口未返回投稿（未登录时该接口会被 412 风控拦截）。"

    out = {
        "uid": mid,
        "page": page,
        "api_page": page_info.get("pn"),
        "page_size": page_size,
        "order": order,
        "keyword": keyword,
        "total": total,
        "count": len(items_all),
        "items": items_all,
        "hint": hint,
        "max_pages": MAX_PAGES,
    }
    out.update(paging_meta(want, done, page, stop))
    return out

"""2.1 综合搜索结果。"""

from __future__ import annotations

from typing import Any

from .. import constants as C
from ..client import BiliClient, gaia_slots
from ..errors import BiliError
from ..utils import parse_duration, strip_html
from .paging import MAX_PAGES, clamp_pages, page_detail, paging_meta

MAX_PAGE_SIZE = 50


def _fetch_page(client: BiliClient, keyword: str, order: str, page: int, page_size: int,
                duration: int, pubtime_begin_s: int | None,
                pubtime_end_s: int | None) -> dict:
    params: dict[str, Any] = {
        "search_type": "video",
        "keyword": keyword,
        "order": order,
        "page": page,
        "page_size": page_size,
        "duration": duration,
        "from_source": "",
        "web_location": 1430654,
        # gaia 指纹槽位：`space/wbi/acc/info` 已被单变量消融证明为准入必要条件，
        # 这里补齐以与其他接口一致。**诚实标注**：实测它对搜索接口的 v_voucher
        # 软风控命中率只有 50%→40%（交替 A/B，10 样本内不显著），不是解药。
        **gaia_slots(),
    }
    if pubtime_begin_s is not None:
        params["pubtime_begin_s"] = int(pubtime_begin_s)
        params["pubtime_end_s"] = int(pubtime_end_s)
    data = client.request_json(C.EP_SEARCH_TYPE, params=params, wbi=True,
                               headers={"Referer": "https://search.bilibili.com/"})
    return data if isinstance(data, dict) else {}


def search_videos(
    client: BiliClient,
    keyword: str,
    order: str = "totalrank",
    page: int = 1,
    page_size: int = 30,
    duration: int = 0,
    pubtime_begin_s: int | None = None,
    pubtime_end_s: int | None = None,
    pages: int = 1,
) -> dict[str, Any]:
    """综合搜索（video 分区）。

    `page` 是起始页，`pages` 是从它开始**连续抓几页**（1..250）。多页时 `items`
    是各页合并后的列表，并附带 `per_page` 明细与 `pages_fetched`。

    参数校验严格：日期区间必须成对且 begin < end（需求明确要求）。
    """
    keyword = (keyword or "").strip()
    if not keyword:
        raise ValueError("keyword 不能为空")
    if order not in C.SEARCH_ORDERS:
        raise ValueError(f"order 非法: {order}，可选 {list(C.SEARCH_ORDERS)}")
    if duration not in C.SEARCH_DURATIONS:
        raise ValueError(f"duration 非法: {duration}，可选 {list(C.SEARCH_DURATIONS)}")
    if page < 1:
        raise ValueError("page 从 1 开始")
    page = int(page)
    want = clamp_pages(pages)
    page_size = max(1, min(int(page_size), MAX_PAGE_SIZE))

    if pubtime_begin_s is not None or pubtime_end_s is not None:
        if pubtime_begin_s is None or pubtime_end_s is None:
            raise ValueError("开始日期与结束日期必须同时提供")
        if int(pubtime_begin_s) >= int(pubtime_end_s):
            raise ValueError("开始日期必须小于结束日期")

    items_all: list[dict] = []
    done: list[dict] = []
    meta: dict = {}
    stop: str | None = None
    for i in range(want):
        cur = page + i
        body = _fetch_page(client, keyword, order, cur, page_size, duration,
                           pubtime_begin_s, pubtime_end_s)
        api_page = body.get("page")
        try:
            api_page_int = int(api_page) if api_page is not None else None
        except (TypeError, ValueError):
            api_page_int = None
        # 越界页保护（实测，见 tests/probe_search_paging_bound.py）
        # 请求 page 超过接口的 numPages 时，服务端**不报错也不返回空**，而是把 page
        # 回退掉（page=40 -> api_page=34），返回的是**别的页**的数据。起始页越界必须
        # 报错；后续页越界说明已经抓到末尾，停止即可。
        if api_page_int is not None and api_page_int != cur:
            if i == 0:
                raise BiliError(
                    f"搜索第 {cur} 页超出接口范围：服务端把它回退成了第 {api_page_int} 页"
                    f"（该关键词 numPages={body.get('numPages')}）。继续下去拿到的会是"
                    f"别的页的数据，请把页码收敛到 1..{body.get('numPages') or '?'} 之间。",
                    url=C.EP_SEARCH_TYPE)
            stop = "api_page_mismatch"
            break
        page_items = [normalize(item) for item in body.get("result") or []]
        items_all.extend(page_items)
        done.append(page_detail(cur, len(page_items)))
        meta = body
        num_pages = body.get("numPages")
        if not page_items:
            stop = "empty_page"
            break
        try:
            # 服务端对搜索结果有条数上限（实测关键词只给 1000 条 / numPages=34），
            # 到顶后必须主动停 —— 再往后请求会被回退成别的页，拿到的是重复数据。
            if num_pages and cur >= int(num_pages):
                stop = "reached_num_pages"
                break
        except (TypeError, ValueError):
            pass

    out = {
        "keyword": keyword,
        "order": order,
        "order_label": C.SEARCH_ORDERS[order],
        "duration": duration,
        "duration_label": C.SEARCH_DURATIONS[duration],
        "pubtime_begin_s": pubtime_begin_s,
        "pubtime_end_s": pubtime_end_s,
        "page": page,
        "api_page": meta.get("page"),
        "page_size": page_size,
        "total": meta.get("numResults", 0),
        "total_pages": meta.get("numPages"),
        "count": len(items_all),
        "items": items_all,
        "max_pages": MAX_PAGES,
    }
    out.update(paging_meta(want, done, page, stop))
    return out


def normalize(item: dict) -> dict[str, Any]:
    """把搜索条目转成稳定结构（去掉 <em> 标签、统一时长/时间）。"""
    return {
        "bvid": item.get("bvid"),
        "aid": item.get("aid") or item.get("id"),
        "title": strip_html(item.get("title")),
        "author": item.get("author"),
        "mid": item.get("mid"),
        "play": item.get("play"),
        "danmaku": item.get("video_review"),
        "favorites": item.get("favorites"),
        "duration": item.get("duration"),
        "duration_seconds": parse_duration(item.get("duration")),
        "pubdate": item.get("pubdate"),
        "description": strip_html(item.get("description")),
        "tag": item.get("tag"),
        "typename": item.get("typename"),
        "arcurl": item.get("arcurl"),
        "pic": item.get("pic"),
        "is_pay": item.get("is_pay"),
        "is_union_video": item.get("is_union_video"),
    }


def search_user(client: BiliClient, username: str) -> list[dict]:
    """按用户名搜用户（用于把"准确用户名"解析成 uid）。"""
    params = {
        "search_type": "bili_user",
        "keyword": (username or "").strip(),
        "page": 1,
        "page_size": 30,
        "from_source": "",
        "web_location": 1430654,
        **gaia_slots(),
    }
    data = client.request_json(C.EP_SEARCH_USER, params=params, wbi=True,
                               headers={"Referer": "https://search.bilibili.com/"})
    out = []
    for item in (data or {}).get("result") or []:
        if item.get("type") != "bili_user" and "mid" not in item:
            continue
        out.append({
            "mid": item.get("mid"),
            "uname": strip_html(item.get("uname")),
            "usign": item.get("usign"),
            "fans": item.get("fans"),
            "videos": item.get("videos"),
            "level": item.get("level"),
            "official_verify": item.get("official_verify"),
        })
    return out


def resolve_username(client: BiliClient, username: str) -> int:
    """精确用户名 -> uid；要求 uname 完全相等，避免认错人。"""
    target = (username or "").strip()
    candidates = search_user(client, target)
    exact = [c for c in candidates if c.get("uname") == target]
    if not exact:
        names = ", ".join(f"{c.get('uname')}({c.get('mid')})" for c in candidates[:8])
        raise ValueError(f"没有与 “{target}” 精确匹配的用户名。近似结果: {names or '无'}")
    if len(exact) > 1:
        raise ValueError(
            f"“{target}” 匹配到多个账号，请直接用 uid: "
            + ", ".join(str(c.get("mid")) for c in exact)
        )
    return int(exact[0]["mid"])

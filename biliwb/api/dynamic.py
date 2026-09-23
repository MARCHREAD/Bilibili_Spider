"""2.8 用户动态列表（图文/视频/转发）。"""

from __future__ import annotations

from typing import Any

from .. import constants as C
from ..client import BiliClient
from ..utils import ts_to_str
from .paging import MAX_PAGES, clamp_pages, page_detail, paging_meta


def user_dynamics(client: BiliClient, ref: str, page: int = 1, offset: str = "",
                  pages: int = 1) -> dict[str, Any]:
    """动态列表是 offset 游标分页；page 仅表示第几批，offset 可续传。

    `pages` = 从这一批开始连续取几批（1..250）；多批返回的 `offset_out` 是**最后一批**
    的游标，`per_page` 给出每批条数。
    """
    from .user import resolve_mid

    mid = resolve_mid(client, ref)
    page = max(1, int(page))
    want = clamp_pages(pages)

    items_all: list[dict] = []
    done: list[dict] = []
    meta: dict = {}
    cur_offset = offset
    stop: str | None = None
    for i in range(want):
        cur_page = page + i
        params = {"host_mid": mid, "web_location": 333.1387, "timezone_offset": -480}
        if cur_offset:
            params["offset"] = cur_offset
        elif cur_page > 1:
            raise ValueError("动态分页是游标式的：第 2 页起必须传上一页返回的 offset")

        data = client.request_json(
            C.EP_DYN_SPACE, params=params,
            headers={"Referer": f"https://space.bilibili.com/{mid}/dynamic"},
        ) or {}
        batch = [_normalize(item) for item in (data.get("items") or [])]
        items_all.extend(batch)
        done.append(page_detail(cur_page, len(batch)))
        meta = data
        nxt = data.get("offset")
        if not batch or not data.get("has_more") or not nxt or nxt == cur_offset:
            stop = "no_more" if (not batch or not data.get("has_more")) else "no_next_offset"
            break
        cur_offset = nxt

    out = {
        "uid": mid,
        "page": page,
        "offset_in": offset,
        "offset_out": meta.get("offset"),
        "has_more": meta.get("has_more"),
        "total": meta.get("total"),
        "update_num": meta.get("update_num"),
        "count": len(items_all),
        "items": items_all,
        "max_pages": MAX_PAGES,
    }
    out.update(paging_meta(want, done, page, stop))
    return out


def _normalize(item: dict) -> dict[str, Any]:
    dyn_id = item.get("id_str") or item.get("id")
    modules = item.get("modules") or {}
    author = (modules.get("module_author") or {})
    dynamic = (modules.get("module_dynamic") or {})
    stat = (modules.get("module_stat") or {})

    major = dynamic.get("major") or {}
    kind = None
    payload: dict[str, Any] = {}
    if major.get("archive"):
        kind = "video"
        arc = major["archive"]
        payload = {"bvid": arc.get("bvid"), "title": arc.get("title"),
                   "desc": arc.get("desc"), "duration_text": arc.get("duration_text"),
                   "cover": arc.get("cover"), "stat": arc.get("stat")}
    elif major.get("opus"):
        kind = "opus"
        opus = major["opus"]
        payload = {"title": opus.get("title"),
                   "summary": ((opus.get("summary") or {}).get("text")),
                   "pics": [p.get("url") for p in (opus.get("pics") or [])]}
    elif major.get("draw"):
        kind = "draw"
        draw = major["draw"]
        payload = {"items": [d.get("src") for d in (draw.get("items") or [])]}
    elif major.get("article"):
        kind = "article"
        art = major["article"]
        payload = {"title": art.get("title"), "desc": art.get("desc"),
                   "covers": art.get("covers")}
    elif major.get("live_rcmd"):
        kind = "live"
    elif dynamic.get("desc"):
        kind = "text"

    desc_text = (dynamic.get("desc") or {}).get("text") if dynamic.get("desc") else None
    return {
        "id": dyn_id,
        "type": item.get("type"),
        "kind": kind,
        "visible": item.get("visible"),
        "author": {
            "mid": author.get("mid"),
            "name": author.get("name"),
            "face": author.get("face"),
            "pub_time": author.get("pub_time"),
            "pub_ts": author.get("pub_ts"),
            "pub_time_str": ts_to_str(author.get("pub_ts")),
        },
        "text": desc_text,
        "payload": payload,
        "stat": {
            "comment": ((stat.get("comment") or {}).get("count")),
            "like": ((stat.get("like") or {}).get("count")),
            "repost": ((stat.get("repost") or {}).get("count")),
        },
    }

"""业务 API 门面：把 8 项能力收敛到一个对象上。

    api = BiliAPI(client)
    api.search("原神", order="click", page=2)
    api.video("BV1BHez6cEEm")
    ...
"""

from __future__ import annotations

from pathlib import Path

from ..client import BiliClient
from ..login import LoginManager
from . import comment as comment_mod
from . import danmaku as danmaku_mod
from . import dynamic as dynamic_mod
from . import search as search_mod
from . import user as user_mod
from . import video as video_mod


class BiliAPI:
    def __init__(self, client: BiliClient, session_path: str | Path = "session.txt") -> None:
        self.client = client
        self.login = LoginManager(client, session_path)
        # 评论是游标式分页：缓存 (oid, sort) -> [已见过的 offset 链]
        self._reply_offsets: dict[tuple, list[str]] = {}

    # -------------------------------------------------- 2.1 综合搜索
    def search(self, keyword: str, order: str = "totalrank", page: int = 1,
               page_size: int = 30, duration: int = 0,
               pubtime_begin_s: int | None = None,
               pubtime_end_s: int | None = None, pages: int = 1) -> dict:
        return search_mod.search_videos(
            self.client, keyword, order=order, page=page, page_size=page_size,
            duration=duration, pubtime_begin_s=pubtime_begin_s,
            pubtime_end_s=pubtime_end_s, pages=pages,
        )

    # -------------------------------------------------- 2.2 视频详情
    def video(self, ref: str, with_subtitle: bool = True, with_subtitle_text: bool = False,
              with_tags: bool = True, with_pinned_comment: bool = True,
              with_page_probe: bool = False) -> dict:
        return video_mod.video_detail(
            self.client, ref, with_subtitle=with_subtitle,
            with_subtitle_text=with_subtitle_text, with_tags=with_tags,
            with_pinned_comment=with_pinned_comment, with_page_probe=with_page_probe,
        )

    # -------------------------------------------------- 2.3 评论
    def comments(self, ref: str, page: int = 1, page_size: int = 20, sort: str = "hot",
                 with_sub: bool = True, sub_pages: int = 1, pages: int = 1) -> dict:
        return comment_mod.video_comments(
            self.client, ref, self._reply_offsets, page=page, page_size=page_size,
            sort=sort, with_sub=with_sub, sub_pages=sub_pages, pages=pages,
        )

    # -------------------------------------------------- 2.4 弹幕
    def danmaku(self, ref: str, segment_index: int = 0, all_segments: bool = False,
                max_segments: int = 40, resolve_senders: bool = False,
                candidate_mids: list[int] | None = None,
                enrich_limit: int = 0, pool_pages: int = 5) -> dict:
        return danmaku_mod.video_danmaku(
            self.client, ref, segment_index=segment_index, all_segments=all_segments,
            max_segments=max_segments, resolve_senders=resolve_senders,
            candidate_mids=candidate_mids, enrich_limit=enrich_limit,
            pool_pages=pool_pages,
        )

    # -------------------------------------------------- 2.5 用户资料
    def user(self, ref: str, with_followings: bool = False, with_followers: bool = False,
             list_pages: int = 1, list_page_size: int = 50,
             with_dynamic_scan: bool = False) -> dict:
        return user_mod.user_profile(
            self.client, ref, with_followings=with_followings,
            with_followers=with_followers, list_pages=list_pages,
            list_page_size=list_page_size, with_dynamic_scan=with_dynamic_scan,
        )

    # -------------------------------------------------- 2.6 作者视频列表
    def user_videos(self, ref: str, page: int = 1, page_size: int = 30,
                    order: str = "pubdate", keyword: str = "", tid: int = 0,
                    pages: int = 1) -> dict:
        return user_mod.user_videos(
            self.client, ref, page=page, page_size=page_size, order=order,
            keyword=keyword, tid=tid, pages=pages,
        )

    # -------------------------------------------------- 2.7 视频流
    def stream(self, ref: str, qn: int = 80, fnval: int = 4048) -> dict:
        return video_mod.video_stream(self.client, ref, qn=qn, fnval=fnval)

    # -------------------------------------------------- 2.8 用户动态
    def dynamics(self, ref: str, page: int = 1, offset: str = "",
                 pages: int = 1) -> dict:
        return dynamic_mod.user_dynamics(self.client, ref, page=page, offset=offset,
                                         pages=pages)


__all__ = ["BiliAPI"]

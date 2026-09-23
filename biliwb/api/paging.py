"""分页通用：把"抓取几页"收进安全范围，并统一逐页汇总的形状。

2.1 综合搜索 / 2.3 视频评论 / 2.6 作者视频列表 / 2.8 用户动态 都支持一次抓多页。

上限 250 是**硬约束**（`MAX_PAGES`）：既挡住误填（99999 会把任务拖死），
也避免单次调用发出过多请求。所有入口都过 `clamp_pages`，不允许绕过。
"""

from __future__ import annotations

MAX_PAGES = 250


def clamp_pages(value, default: int = 1) -> int:
    """把"抓取几页"归一化到 1..MAX_PAGES。

    None / "" / 非法值 -> default；超上限 -> 截到上限（而不是报错，
    因为批量任务里一个填错的值不该让整条目标失败）。
    """
    if value is None or value == "":
        return max(1, min(int(default), MAX_PAGES))
    try:
        n = int(value)
    except (TypeError, ValueError):
        return max(1, min(int(default), MAX_PAGES))
    return max(1, min(n, MAX_PAGES))


def page_detail(page_no: int, count: int, **extra) -> dict:
    """单页明细（汇总进返回体的 per_page，便于核对抓到哪几页）。"""
    row = {"page": page_no, "count": count}
    row.update(extra)
    return row


# 为什么没抓满请求的页数 —— 只给一个 truncated=true 用户看不懂
STOP_REASON_TEXT = {
    "reached_pages": "已抓满请求的页数",
    "reached_num_pages": "已到服务端结果上限（该关键词只下发这么多页）",
    "empty_page": "服务端返回空页，没有更多数据",
    "api_page_mismatch": "页码越界（服务端把请求页回退了），已停止",
    "cursor_end": "接口标记已到末页",
    "no_more": "接口标记没有更多数据",
    "no_next_offset": "游标不再前进",
}


def paging_meta(want: int, done: list[dict], start_page: int,
                stop_reason: str | None = None) -> dict:
    """多页返回体的公共字段。"""
    fetched = len(done)
    if stop_reason is None:
        stop_reason = "reached_pages" if fetched >= want else "empty_page"
    return {
        "pages_requested": want,
        "pages_fetched": fetched,
        "page_start": start_page,
        "page_end": (start_page + fetched - 1) if fetched else None,
        "per_page": done,
        "truncated": fetched < want,
        "stop_reason": stop_reason,
        "stop_reason_text": STOP_REASON_TEXT.get(stop_reason, stop_reason),
    }

"""「抓取页数」的离线验证（**零网络请求**）。

需求：每个有页码的接口再来一个"抓取几页"的设定，**上限 250**。
覆盖 2.1 搜索 / 2.3 评论 / 2.6 投稿 / 2.8 动态，以及上限截断与越界停止。

用法：python tests/test_paging_multipage.py
"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb.api import comment as comment_mod
from biliwb.api import dynamic as dynamic_mod
from biliwb.api import search as search_mod
from biliwb.api import user as user_mod
from biliwb.api.paging import MAX_PAGES, clamp_pages
from biliwb.client import BiliClient
from biliwb.errors import BiliError

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK ] {label:<50} {detail}", file=sys.stderr)
    else:
        FAIL += 1
        print(f"  [BAD] {label:<50} {detail}", file=sys.stderr)


class SeqClient(BiliClient):
    """按调用顺序返回预设响应的假 client。"""

    def __init__(self, replies: list[dict]) -> None:
        super().__init__(min_delay=0.0, jitter=0.0)
        self._wbi_keys = ("img", "sub")
        self._replies = list(replies)
        self.calls: list[dict] = []

    def request_json(self, url, params=None, **kw):  # type: ignore[override]
        self.calls.append(dict(params or {}))
        if not self._replies:
            raise AssertionError("多余的请求")
        return self._replies.pop(0)


def search_body(page: int, n: int = 30, num_pages: int = 34) -> dict:
    return {"result": [{"bvid": f"BV{page}-{i}", "title": f"t"} for i in range(n)],
            "numResults": 1000, "numPages": num_pages, "page": page}


def main() -> int:
    print("== 抓取页数（离线）==", file=sys.stderr)

    # 1. 上限钳制
    check("MAX_PAGES == 250", MAX_PAGES == 250, str(MAX_PAGES))
    for value, want in ((1, 1), (0, 1), (-5, 1), (250, 250), (251, 250), (99999, 250),
                        ("7", 7), ("abc", 1), (None, 1), ("", 1)):
        got = clamp_pages(value)
        check(f"clamp_pages({value!r}) -> {want}", got == want, f"got={got}")

    # 2. 搜索：连续 3 页合并
    cli = SeqClient([search_body(3), search_body(4), search_body(5)])
    out = search_mod.search_videos(cli, "原神", page=3, pages=3, page_size=30)
    pages_hit = [c.get("page") for c in cli.calls]
    check("搜索按 page..page+N-1 依次请求", pages_hit == [3, 4, 5], str(pages_hit))
    check("搜索合并条数 = 各页之和", out.get("count") == 90, str(out.get("count")))
    check("搜索返回逐页明细", [p["count"] for p in out.get("per_page", [])] == [30, 30, 30],
          str(out.get("per_page")))
    check("搜索给出页区间", out.get("page_start") == 3 and out.get("page_end") == 5,
          f"{out.get('page_start')}..{out.get('page_end')}")
    check("搜索未提前结束", out.get("truncated") is False, str(out.get("truncated")))
    check("抓满时 stop_reason=reached_pages",
          out.get("stop_reason") == "reached_pages", str(out.get("stop_reason")))
    check("搜索暴露上限", out.get("max_pages") == 250, str(out.get("max_pages")))

    # 3. 搜索：抓到末页就停（numPages=5，从第 4 页抓 10 页）
    cli = SeqClient([search_body(4, n=30, num_pages=5), search_body(5, n=10, num_pages=5)])
    out = search_mod.search_videos(cli, "原神", page=4, pages=10)
    check("到 numPages 停止（只发 2 次请求）", len(cli.calls) == 2, str(len(cli.calls)))
    check("停止时标记 truncated", out.get("truncated") is True and out.get("pages_fetched") == 2,
          f"fetched={out.get('pages_fetched')} truncated={out.get('truncated')}")
    check("到 numPages 时说明原因 reached_num_pages",
          out.get("stop_reason") == "reached_num_pages"
          and "服务端结果上限" in (out.get("stop_reason_text") or ""),
          f"{out.get('stop_reason')} / {out.get('stop_reason_text')}")
    check("停止时条数正确", out.get("count") == 40, str(out.get("count")))

    # 4. 搜索：起始页越界仍必须报错（不能把别人的页当本页）
    cli = SeqClient([search_body(34, n=10)])
    try:
        search_mod.search_videos(cli, "原神", page=40, pages=3)
        check("起始页越界应报错", False, "没有抛异常")
    except BiliError as exc:
        check("起始页越界报错", True, str(exc)[:44])

    # 5. 搜索：后续页越界 -> 停止而不是报错
    cli = SeqClient([search_body(34, n=10), search_body(1, n=30)])   # 第 35 页被回退成 1
    out = search_mod.search_videos(cli, "原神", page=34, pages=5)
    check("后续页越界只停止不报错", out.get("pages_fetched") == 1 and out.get("truncated") is True,
          f"fetched={out.get('pages_fetched')}")

    # 6. 投稿：pn 连续推进 + 空页停止
    def arc(pn: int, n: int) -> dict:
        return {"list": {"vlist": [{"bvid": f"BV{pn}-{i}"} for i in range(n)]},
                "page": {"pn": pn, "count": 100}}

    cli = SeqClient([arc(1, 30), arc(2, 30), arc(3, 0)])
    out = user_mod.user_videos(cli, "480959917", page=1, pages=5)
    check("投稿按 pn 依次请求", [c.get("pn") for c in cli.calls] == [1, 2, 3],
          str([c.get("pn") for c in cli.calls]))
    check("投稿空页即停", out.get("pages_fetched") == 3 and out.get("count") == 60,
          f"fetched={out.get('pages_fetched')} count={out.get('count')}")

    # 7. 动态：offset 链式推进
    def dyn(offset: str | None, n: int, has_more: bool = True) -> dict:
        d = {"items": [{"id_str": f"d{i}"} for i in range(n)], "has_more": has_more}
        if offset:
            d["offset"] = offset
        return d

    cli = SeqClient([dyn("o1", 10), dyn("o2", 10), dyn("o3", 0, has_more=False)])
    out = dynamic_mod.user_dynamics(cli, "480959917", page=1, pages=5)
    check("动态首批发无 offset", "offset" not in cli.calls[0], str(cli.calls[0].keys()))
    check("动态后续带上一批 offset", cli.calls[1].get("offset") == "o1", str(cli.calls[1].get("offset")))
    check("动态空批即停", out.get("pages_fetched") == 3 and out.get("count") == 20,
          f"fetched={out.get('pages_fetched')} count={out.get('count')}")
    check("动态 offset_out 取最后一批（而非第一批）",
          out.get("offset_out") == "o3", f"offset_out={out.get('offset_out')} (首批是 o1)")

    # 8. 评论：游标式多页（直接给缓存喂数据，避免真请求）
    replies = [{"replies": [{"rpid": i, "content": {"message": "x"}, "member": {"mid": str(i)}}],
                "cursor": {"all_count": 100, "is_end": 0,
                           "pagination_reply": {"next_offset": f"off{i}"}}} for i in range(1, 4)]
    cli = SeqClient(replies)
    out = comment_mod.video_comments(cli, "BV1X9eb6tEvy", {}, page=1, pages=3, with_sub=False)
    check("评论抓 3 页", out.get("pages_fetched") == 3, str(out.get("pages_fetched")))
    check("评论条数合并", out.get("count") == 3, str(out.get("count")))
    check("评论 per_page 记录 is_end",
          all("is_end" in p for p in out.get("per_page", [])), str(out.get("per_page")))
    check("评论把起始页当 page", out.get("page") == 1, str(out.get("page")))
    check("评论暴露上限", out.get("max_pages") == 250, str(out.get("max_pages")))

    # 9. 单页行为保持兼容（pages=1 时字段仍在，结构不变）
    cli = SeqClient([search_body(1)])
    out = search_mod.search_videos(cli, "原神", page=1)
    check("默认 pages=1 只请求一次", len(cli.calls) == 1, str(len(cli.calls)))
    check("默认单页 count == 本页条数", out.get("count") == 30, str(out.get("count")))

    print(f"\n== {PASS} passed, {FAIL} failed ==", file=sys.stderr)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

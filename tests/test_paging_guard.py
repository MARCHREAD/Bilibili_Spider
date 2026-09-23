"""分页一致性防护的离线验证（**零网络请求**）。

实测背景（见 tests/probe_search_paging_bound.py / probe_user_videos_bound.py）：
  * 搜索接口 page 超出 numPages 时**不报错**，而是把 page 回退（page=40 -> api_page=34），
    返回的是**别的页**的数据 —— 旧实现会把它当成本页交给用户；
  * 作者投稿接口 pn 越界则返回**空列表**且 pn 不变，属于正常"末页"语义；
  * 评论接口"本页为空 + 服务端称未到底 + 总数非零"是自相矛盾的组合，属于疑似截断。

用法：python tests/test_paging_guard.py
"""

from __future__ import annotations

import pathlib
import sys
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb.api import comment as comment_mod
from biliwb.api import search as search_mod
from biliwb.api import user as user_mod
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


def fake_client(body: dict) -> BiliClient:
    cli = BiliClient(min_delay=0.0, jitter=0.0)
    cli._wbi_keys = ("img", "sub")
    cli.request_json = lambda *a, **kw: body   # type: ignore[assignment]
    return cli


def search_body(page: int, api_page: int, n: int = 30, num_pages: int = 34) -> dict:
    return {"result": [{"bvid": f"BV{i}", "title": f"t{i}"} for i in range(n)],
            "numResults": 1000, "numPages": num_pages, "page": api_page}


def main() -> int:
    print("== 分页一致性防护（离线）==", file=sys.stderr)

    # ---- 搜索：越界被回退必须报错，而不是把别的页当本页 ----
    cli = fake_client(search_body(page=40, api_page=34))
    try:
        search_mod.search_videos(cli, "原神", page=40, page_size=30)
        check("搜索越界应报错", False, "没有抛异常")
    except BiliError as exc:
        check("搜索越界报错", True, str(exc)[:60])
        check("错误信息给出实际页码范围", "34" in str(exc), "含 numPages")

    cli = fake_client(search_body(page=1, api_page=1))
    out = search_mod.search_videos(cli, "原神", page=1, page_size=30)
    check("正常页不误报", out.get("api_page") == 1 and out.get("count") == 30,
          f"api_page={out.get('api_page')} count={out.get('count')}")

    cli = fake_client(search_body(page=34, api_page=34, n=10))
    out = search_mod.search_videos(cli, "原神", page=34, page_size=30)
    check("最后一页正常返回", out.get("count") == 10 and out.get("api_page") == 34,
          f"count={out.get('count')}")

    # api 不返回 page 字段时不能误判
    cli = fake_client({"result": [{"bvid": "BV1"}], "numResults": 10, "numPages": 1})
    out = search_mod.search_videos(cli, "原神", page=7, page_size=30)
    check("缺少 page 字段时不误报", out.get("count") == 1 and out.get("api_page") is None,
          f"api_page={out.get('api_page')}")

    # ---- 作者投稿：越界是空列表（正常末页语义），hint 不能说是"未登录" ----
    cli = fake_client({"list": {"vlist": []}, "page": {"pn": 70, "count": 2060}})
    out = user_mod.user_videos(cli, "86889715", page=70, page_size=30)
    check("投稿越界 hint 说明已到末页",
          out.get("count") == 0 and "末页" in (out.get("hint") or ""),
          f"hint={out.get('hint')}")
    check("投稿越界保留 api_page 供核对", out.get("api_page") == 70, str(out.get("api_page")))

    cli = fake_client({"list": {"vlist": [{"bvid": "BV1"}]},
                       "page": {"pn": 1, "count": 2060}})
    out = user_mod.user_videos(cli, "86889715", page=1, page_size=30)
    check("投稿首页无 hint", out.get("hint") is None and out.get("count") == 1, str(out.get("hint")))

    # ---- 评论：空页 + 未到底 + 总数非零 -> 标记疑似截断 ----
    truncated = {"replies": [], "cursor": {"is_end": 0, "all_count": 500,
                                           "pagination_reply": {"next_offset": "abc"}}}
    cli = fake_client(truncated)
    with mock.patch.object(comment_mod, "_fetch_main", return_value=truncated):
        out = comment_mod.video_comments(cli, "BV1X9eb6tEvy", {}, page=1)
    check("评论疑似截断被标记", out.get("suspicious_empty_page") is True,
          f"flag={out.get('suspicious_empty_page')} hint={(out.get('hint') or '')[:40]}")

    real_end = {"replies": [], "cursor": {"is_end": 1, "all_count": 500}}
    with mock.patch.object(comment_mod, "_fetch_main", return_value=real_end):
        out = comment_mod.video_comments(cli, "BV1X9eb6tEvy", {}, page=1)
    check("真正到底不被误标", out.get("suspicious_empty_page") is None,
          f"flag={out.get('suspicious_empty_page')}")

    empty_video = {"replies": [], "cursor": {"is_end": 1, "all_count": 0}}
    with mock.patch.object(comment_mod, "_fetch_main", return_value=empty_video):
        out = comment_mod.video_comments(cli, "BV1X9eb6tEvy", {}, page=1)
    check("零评论视频不被误标", out.get("suspicious_empty_page") is None,
          f"flag={out.get('suspicious_empty_page')}")

    print(f"\n== {PASS} passed, {FAIL} failed ==", file=sys.stderr)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

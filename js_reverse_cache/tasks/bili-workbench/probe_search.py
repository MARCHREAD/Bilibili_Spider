"""搜索接口准入消融（v_voucher 软风控定位）。

现象：`x/web-interface/wbi/search/type` 返回 HTTP 200、code 0，
     但 data 只有 {"v_voucher": "..."}，没有 result —— 这是"200 填充值惩罚"，
     不是空结果。必须与"真的没有搜索结果"区分开。

自变量（一次一个）：
  1. 是否携带 gaia 指纹槽位
  2. wbi 路径 vs 非 wbi 路径
  3. 是否先访问搜索页暖场（cookie/`buvid` 绑定）
  4. search.bilibili.com SSR HTML 是否自带结果（browser-free 备用路径）

用法：python probe_search.py
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402

GAIA = {
    "dm_img_list": "[]",
    "dm_img_str": C.GAIA_DM_IMG_STR,
    "dm_cover_img_str": C.GAIA_DM_COVER_IMG_STR,
    "dm_img_inter": C.GAIA_DM_IMG_INTER,
}

KW = "原神"
BASE = {
    "search_type": "video", "keyword": KW, "order": "totalrank", "page": 1,
    "page_size": 30, "duration": 0, "from_source": "", "web_location": 1430654,
}


def classify(data) -> str:
    if not isinstance(data, dict):
        return f"non-dict {type(data).__name__}"
    if "v_voucher" in data and "result" not in data:
        return f"SOFT-RISK v_voucher={str(data['v_voucher'])[:16]}..."
    res = data.get("result")
    if isinstance(res, list):
        return f"OK result={len(res)}"
    return f"OK keys={list(data.keys())[:8]}"


def main() -> int:
    cli = BiliClient(min_delay=1.7, jitter=0.3, retries=0)
    cli.bootstrap()
    cli.gen_ticket()
    cli.wbi_keys(refresh=True)

    def attempt(label, url, params, headers=None, wbi=True):
        try:
            data = cli.request_json(url, params=params, headers=headers, wbi=wbi, retries=0)
            verdict = classify(data)
        except Exception as exc:
            verdict = f"{type(exc).__name__}: {exc}"
        print(f"  {label:<44} -> {verdict}", file=sys.stderr)
        return verdict

    print("== 搜索准入消融 ==", file=sys.stderr)
    attempt("wbi, no gaia", C.EP_SEARCH_TYPE, BASE)
    attempt("wbi, +gaia", C.EP_SEARCH_TYPE, {**BASE, **GAIA})
    attempt("non-wbi path", f"{C.API}/x/web-interface/search/type", BASE, wbi=False)
    attempt("wbi, no cookie-ish params", C.EP_SEARCH_TYPE,
            {**BASE, **GAIA, "web_location": 1430654, "order_sort": 0})

    print("== 搜索页 SSR HTML 备用路径 ==", file=sys.stderr)
    html = cli.get_text(
        f"https://search.bilibili.com/video?keyword={KW}&order=totalrank&page=1",
        headers={"Referer": "https://search.bilibili.com/"},
    )
    info = {"bytes": len(html)}
    for needle in ["__pinia", "__INITIAL_STATE__", "window.__playinfo", "video-list", "bvid"]:
        info[needle] = html.count(needle)
    bvids = re.findall(r"BV[0-9A-Za-z]{10}", html)
    info["unique_bvids"] = len(set(bvids))
    info["sample_bvids"] = list(dict.fromkeys(bvids))[:5]
    print(f"  SSR HTML -> {json.dumps(info, ensure_ascii=False)}", file=sys.stderr)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

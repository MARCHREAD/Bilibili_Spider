"""风控准入矩阵（transport/host admission ablation）。

问题：同样一条接口，live 浏览器 200，本机 Python 却 -352 / 412。
候选自变量（一次只动一个）：
  A. Referer / Origin 是否指向该接口所属站点（space.* vs www.*）
  B. 是否携带 gaia 指纹槽位（dm_img_list / dm_img_str / dm_cover_img_str / dm_img_inter）
  C. 分页大小 ps

用法：python probe_risk.py
"""

from __future__ import annotations

import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import constants as C  # noqa: E402
from biliwb.client import BiliClient  # noqa: E402

MID = 86889715
SPACE = "https://space.bilibili.com"

GAIA = {
    "dm_img_list": "[]",
    "dm_img_str": C.GAIA_DM_IMG_STR,
    "dm_cover_img_str": C.GAIA_DM_COVER_IMG_STR,
    "dm_img_inter": C.GAIA_DM_IMG_INTER,
}

ACC_BASE = {"mid": MID, "token": "", "platform": "web", "web_location": 1550101}
ARC_BASE = {
    "pn": 1, "tid": 0, "special_type": "", "order": "pubdate", "mid": MID,
    "index": 0, "keyword": "", "platform": "web",
}


def run(cli: BiliClient, label: str, url: str, params: dict, headers: dict, wbi: bool = True) -> str:
    try:
        data = cli.request_json(url, params=params, headers=headers, wbi=wbi, retries=0)
        keys = list(data.keys())[:10] if isinstance(data, dict) else type(data).__name__
        verdict = f"OK keys={keys}"
    except Exception as exc:
        verdict = f"{type(exc).__name__}: {exc}"
    print(f"  {label:<52} -> {verdict}", file=sys.stderr)
    return verdict


def main() -> int:
    cli = BiliClient(min_delay=1.6, jitter=0.3, verbose=False, retries=0)
    cli.bootstrap()
    cli.gen_ticket()
    cli.wbi_keys(refresh=True)

    print("== A. acc/info referer/origin ==", file=sys.stderr)
    run(cli, "www referer (baseline)", C.EP_ACC_INFO, ACC_BASE, {"Referer": C.WWW + "/"})
    run(cli, "space referer+origin", C.EP_ACC_INFO, ACC_BASE,
        {"Referer": f"{SPACE}/{MID}", "Origin": SPACE})
    run(cli, "space referer + gaia", C.EP_ACC_INFO, {**ACC_BASE, **GAIA},
        {"Referer": f"{SPACE}/{MID}", "Origin": SPACE})
    run(cli, "www referer + gaia", C.EP_ACC_INFO, {**ACC_BASE, **GAIA},
        {"Referer": C.WWW + "/"})

    print("== B. arc/search ==", file=sys.stderr)
    sp = {"Referer": f"{SPACE}/{MID}/upload/video", "Origin": SPACE}
    run(cli, "space referer ps=30", C.EP_ARC_SEARCH, {**ARC_BASE, "ps": 30,
        "order_avoided": "true", "web_location": 333.1387}, sp)
    run(cli, "space referer ps=30 +gaia", C.EP_ARC_SEARCH, {**ARC_BASE, "ps": 30,
        "order_avoided": "true", "web_location": 333.1387, **GAIA}, sp)
    run(cli, "space referer ps=10 +gaia", C.EP_ARC_SEARCH, {**ARC_BASE, "ps": 10,
        "order_avoided": "true", "web_location": 333.1387, **GAIA}, sp)
    run(cli, "space referer ps=30 no-avoided +gaia", C.EP_ARC_SEARCH, {**ARC_BASE, "ps": 30,
        "web_location": 333.1387, **GAIA}, sp)

    print("== C. 双写：先 www 再 space（会话暖场）==", file=sys.stderr)
    run(cli, "warm www view then acc/info", C.EP_VIEW, {"bvid": "BV1BHez6cEEm"}, {"Referer": C.WWW + "/"})
    run(cli, "acc/info after warm", C.EP_ACC_INFO, ACC_BASE, sp)

    print(f"\nhttp_calls={cli.http_calls}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

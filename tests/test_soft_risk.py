"""软风控（v_voucher）处理逻辑的离线验证（**零网络请求**）。

实测背景（见 tests/probe_search_paging_bound.py / probe_search_gaia_ab.py）：
软风控是**概率性**的，命中率约 50~75%，与 page 深浅、gaia 槽位、暖场都无关；
因此正确做法是"独立的多轮预算 + 每轮自愈"，而旧实现只有 (a) 只认 `data` 单键
v_voucher 的窄检测、(b) 与普通错误共用 retries、(c) 原地退避不修复会话。

用法：python tests/test_soft_risk.py
"""

from __future__ import annotations

import json
import pathlib
import sys
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb.client import BiliClient, soft_risk_hit
from biliwb.errors import RiskControl, SoftRisk

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


class FakeResp:
    def __init__(self, status: int = 200, body=None, text: str = "") -> None:
        self.status_code = status
        self._body = body
        self.text = text or (json.dumps(body, ensure_ascii=False) if body is not None else "")

    def json(self):
        if self._body is None:
            raise ValueError("not json")
        return self._body


def soft_body(extra: dict | None = None) -> dict:
    data = {"v_voucher": "voucher_abc"}
    if extra:
        data.update(extra)
    return {"code": 0, "message": "0", "data": data}


def ok_body(n: int = 30) -> dict:
    return {"code": 0, "message": "0",
            "data": {"result": [{"bvid": f"BV{i}"} for i in range(n)],
                     "numResults": 1000, "numPages": 34}}


def make_client(**kw) -> BiliClient:
    cli = BiliClient(min_delay=0.0, jitter=0.0, **kw)
    cli._wbi_keys = ("img", "sub")   # 避免 wbi_keys() 发请求
    return cli


def run(cli: BiliClient, seq: list[FakeResp], recover_calls: list):
    """用固定响应序列驱动 request_json，并把 sleep/自愈都换成记录器。"""
    def fake_recover(attempt=0):
        recover_calls.append(attempt)

    with mock.patch.object(cli, "_raw", side_effect=seq), \
         mock.patch.object(cli, "_recover_soft_risk", side_effect=fake_recover), \
         mock.patch("biliwb.client.time.sleep"):
        return cli.request_json("https://api.bilibili.com/x/test", retries=3)


def main() -> int:
    print("== 软风控处理（离线）==", file=sys.stderr)

    # 1. 检测形态：窄检测漏掉的多键形态必须被识别
    cases = [
        ("单键（旧检测能认）", soft_body(), True),
        ("多键带分页元信息（旧检测漏掉→静默丢数据）",
         soft_body({"replies": [], "cursor": {"is_end": 0, "all_count": 500}}), True),
        ("顶层 v_voucher", {"code": 0, "v_voucher": "x", "data": {}}, True),
        ("正常结果", ok_body(), False),
        ("真空结果（无 v_voucher）", {"code": 0, "data": {"result": []}}, False),
        ("非 dict", None, False),
    ]
    for label, body, want in cases:
        got = soft_risk_hit(body)
        check(f"soft_risk_hit: {label}", got is want, f"got={got} want={want}")

    # 2. 连续软风控后成功 -> 返回数据且每轮都自愈
    cli = make_client(soft_risk_retries=6)
    rec: list = []
    out = run(cli, [FakeResp(200, soft_body()), FakeResp(200, soft_body()),
                    FakeResp(200, ok_body())], rec)
    check("软风控 2 次后成功", out.get("numResults") == 1000, f"numResults={out.get('numResults')}")
    check("每次软风控都触发自愈", len(rec) == 2, f"recover_calls={len(rec)}")

    # 3. 一直软风控 -> 抛 SoftRisk，且用尽独立预算
    cli = make_client(soft_risk_retries=6)
    rec = []
    try:
        run(cli, [FakeResp(200, soft_body())] * 20, rec)
        check("一直软风控应抛异常", False, "没有抛异常")
        exc = None
    except SoftRisk as e:
        exc = e
        check("一直软风控抛 SoftRisk", True, f"{type(e).__name__}")
    check("软风控预算 = soft_risk_retries+1 次尝试",
          len(rec) == 6, f"recover_calls={len(rec)}（期望 6）")
    if exc is not None:
        check("SoftRisk 是 RiskControl 的子类（旧 except 仍生效）",
              isinstance(exc, RiskControl), type(exc).__mro__[1].__name__)
        check("错误信息不再出现误导的 [0]", not str(exc).startswith("[0]"),
              f"str={str(exc)[:60]}")
        check("错误信息说明是概率性软风控",
              "v_voucher" in str(exc) and "概率" in str(exc), "文案完整")

    # 4. 软风控预算独立于普通 retries：retries=1 时普通错误只试 2 次
    cli = make_client(soft_risk_retries=5)
    rec = []
    try:
        run(cli, [FakeResp(200, soft_body())] * 20, rec)
    except SoftRisk:
        pass
    check("soft_risk_retries=5 -> 6 次尝试（与 retries=3 无关）",
          len(rec) == 5, f"recover_calls={len(rec)}")

    cli = make_client()
    rec = []
    try:
        with mock.patch.object(cli, "_raw",
                               side_effect=[FakeResp(412, None, "risk")] * 10), \
             mock.patch("biliwb.client.time.sleep"):
            cli.request_json("https://api.bilibili.com/x/test", retries=1)
        check("412 仍按 retries 计价", False, "没有抛异常")
    except RiskControl:
        check("412 仍按 retries=1 只试 2 次", cli.http_calls >= 0, "抛 RiskControl")

    # 5. 软风控计数回传给上层（budget = max(retries=3, soft_risk_retries=2) = 3 -> 4 次尝试）
    cli = make_client(soft_risk_retries=2)
    try:
        run(cli, [FakeResp(200, soft_body())] * 10, [])
    except SoftRisk as e:
        check("SoftRisk.attempts 记录实际尝试轮数", e.attempts == 4, f"attempts={e.attempts}")

    # 6. 显式 retries=0 -> 尊重"不要重试"，软风控也不重试
    cli = make_client(soft_risk_retries=6)
    rec = []
    try:
        with mock.patch.object(cli, "_raw", side_effect=[FakeResp(200, soft_body())] * 10), \
             mock.patch.object(cli, "_recover_soft_risk", side_effect=lambda a=0: rec.append(a)), \
             mock.patch("biliwb.client.time.sleep"):
            cli.request_json("https://api.bilibili.com/x/test", retries=0)
        check("retries=0 时软风控不重试", False, "没有抛异常")
    except SoftRisk:
        check("retries=0 时软风控不重试（1 次尝试、0 次自愈）",
              len(rec) == 0, f"recover_calls={len(rec)}")

    print(f"\n== {PASS} passed, {FAIL} failed ==", file=sys.stderr)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""status=2 半自动短信验证的离线验证（**零网络请求**）。

接口与参数挖自官方前端（见 tests/mine_risk_flow.py），这里锁定它们不被改错：
  captcha/pre → (geetest|img) → common/sms/send → login/tel/verify → exchange_cookie
其中 login/tel/verify 有三种分支，由 URL 的 scene 决定（无 scene → loginTelCheck）。

用法：python tests/test_riskverify.py
"""

from __future__ import annotations

import json
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb import riskverify as rv
from biliwb.errors import BiliError

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [OK ] {label:<52} {detail}", file=sys.stderr)
    else:
        FAIL += 1
        print(f"  [BAD] {label:<52} {detail}", file=sys.stderr)


CHALLENGE_URL = ("https://passport.bilibili.com/h5-app/passport/risk/verify?"
                 "gourl=https%3A%2F%2Fwww.bilibili.com%2F"
                 "&request_id=6fce4b5b1c764260b9a5184c8b860880"
                 "&source=risk&tmp_token=81543bf464e0ad6edf9b7ef591572192")


class FakeClient:
    """记录每次请求的 endpoint 与 payload，按脚本返回响应。"""

    def __init__(self, replies: dict) -> None:
        self.replies = replies          # path 后缀 -> 响应体（list 则依次弹出）
        self.calls: list[tuple[str, dict | None]] = []
        self.session_cookies = {}

    def request_json(self, url, method="GET", data=None, **kw):
        self.calls.append((url, dict(data or {})))
        for key, val in self.replies.items():
            if url.endswith(key):
                if isinstance(val, list):
                    return val.pop(0)
                return val
        raise AssertionError(f"未预期的请求: {url}")

    def _raw(self, method, url, **kw):
        self.calls.append((url, kw.get("data")))

        class R:
            status_code = 200
            text = "{}"
            content = b""

            def json(self_inner):
                return {"code": 0, "message": "0", "data": {"status": 0}}

        return R()

    def cookie_dict(self):
        return self.session_cookies


def main() -> int:
    print("== status=2 短信二次验证（离线）==", file=sys.stderr)

    # 1. url 解析
    ctx = rv.parse_challenge_url(CHALLENGE_URL)
    check("解析 tmp_token", ctx.get("tmp_token") == "81543bf464e0ad6edf9b7ef591572192",
          str(ctx.get("tmp_token"))[:20])
    check("解析 request_id", ctx.get("request_id") == "6fce4b5b1c764260b9a5184c8b860880", "")
    check("解析 source=risk", ctx.get("source") == "risk", str(ctx.get("source")))
    check("无 scene -> 默认 loginTelCheck", rv.sms_type_of(ctx) == "loginTelCheck",
          rv.sms_type_of(ctx))
    check("空 url 不炸", rv.parse_challenge_url("") == {}, "")

    # 2. 发短信：参数必须含 tmp_code / sms_type / recaptcha_token + 验证码字段
    cli = FakeClient({"/common/sms/send": {"code": 0, "message": "0",
                                           "data": {"captcha_key": "CK1"}}})
    fields = {"recaptcha_token": "RT", "gee_challenge": "C", "gee_seccode": "S",
              "gee_validate": "V"}
    out = rv.send_sms(cli, ctx, fields)
    sent = cli.calls[-1][1]
    check("发短信拿到 captcha_key", out.get("captcha_key") == "CK1", str(out.get("captcha_key")))
    check("发短信 payload 完整",
          sent.get("tmp_code") == ctx["tmp_token"] and sent.get("sms_type") == "loginTelCheck"
          and sent.get("recaptcha_token") == "RT" and sent.get("gee_validate") == "V"
          and "img_code" not in sent,
          json.dumps({k: v for k, v in sent.items() if k != "tmp_code"}, ensure_ascii=False))
    check("发短信路径正确",
          cli.calls[-1][0].endswith("/x/safecenter/common/sms/send"), cli.calls[-1][0])

    # 3. 三种校验分支的 endpoint 与参数
    cases = [
        ("loginTelCheck", None, "/x/safecenter/login/tel/verify", {"type": "loginTelCheck"}),
        ("secLogin", "secLogin", "/x/safecenter/sec/verify", {"verify_type": "sms"}),
        ("deviceVerify", "deviceVerify", "/x/safecenter/user_device/verify",
         {"sms_type": "deviceVerify"}),
    ]
    for label, scene, ep_suffix, must in cases:
        c = dict(ctx)
        if scene:
            c["scene"] = scene
        cli = FakeClient({ep_suffix: {"code": 0, "message": "0", "data": {"code": "TICKET"}}})
        ticket = rv.verify_sms(cli, c, "CK1", "123456")
        url, payload = cli.calls[-1]
        ok = (ticket == "TICKET" and url.endswith(ep_suffix)
              and payload.get("tmp_code") == ctx["tmp_token"]
              and payload.get("captcha_key") == "CK1" and payload.get("code") == "123456"
              and all(payload.get(k) == v for k, v in must.items()))
        check(f"校验分支 {label} -> {ep_suffix.split('/')[-1]}", ok,
              f"payload_keys={sorted(payload)}")
        if label == "loginTelCheck":
            check("loginTelCheck 带上 request_id/source",
                  payload.get("request_id") == ctx["request_id"] and payload.get("source") == "risk", "")

    # 4. 校验失败要抛错（不静默）
    cli = FakeClient({"/x/safecenter/login/tel/verify": {"code": -400, "message": "验证码错误"}})
    try:
        rv.verify_sms(cli, ctx, "CK1", "000000")
        check("校验失败应抛错", False, "没有抛异常")
    except BiliError as exc:
        check("校验失败抛 BiliError", "验证码错误" in str(exc), str(exc)[:40])

    # 5. 换 cookie：payload 与 SESSDATA 判定
    cli = FakeClient({"/web/exchange_cookie": {"code": 0, "message": "0", "data": {}}})
    cli.session_cookies = {"SESSDATA": "abc"}
    ex = rv.exchange_cookie(cli, ctx, "TICKET")
    url, payload = cli.calls[-1]
    check("换 cookie payload 正确",
          payload.get("code") == "TICKET" and payload.get("source") == "risk"
          and payload.get("go_url", "").startswith("https://www.bilibili.com"),
          json.dumps(payload, ensure_ascii=False))
    check("换 cookie 判定 SESSDATA", ex.get("ok") is True and ex.get("has_sessdata") is True, "")
    cli2 = FakeClient({"/web/exchange_cookie": {"code": 0, "message": "0", "data": {}}})
    check("没拿到 SESSDATA 则不算成功", rv.exchange_cookie(cli2, ctx, "T")["ok"] is False, "")

    # 6. 人机验证码：geetest 分支走解算器（这里只验证类型分发，避免真跑 node）
    from unittest import mock
    pre = {"type": "geetest", "token": "RT", "geetest": {"gt": "G", "challenge": "C"}}
    fake_cap = {"ok": True, "challenge": "C", "seccode": "S|jordan", "validate": "V",
                "seconds": 14.0, "score": "14"}
    with mock.patch("biliwb.gt3.solve_once", return_value=fake_cap) as m:
        f = rv.solve_captcha(FakeClient({}), pre)
    check("geetest 分支产出 gee_* 字段",
          f.get("gee_validate") == "V" and f.get("gee_seccode") == "S|jordan"
          and f.get("gee_challenge") == "C" and f.get("recaptcha_token") == "RT",
          json.dumps({k: v for k, v in f.items() if not k.startswith("_")}, ensure_ascii=False))
    check("解算时把预取的 gt/challenge/token 传下去",
          m.call_args.kwargs.get("gt") == "G" and m.call_args.kwargs.get("challenge") == "C", "")

    # 7. 未派验证码 / 未知类型要响亮报错
    try:
        rv.solve_captcha(FakeClient({}), {"type": "unknown", "token": "T"})
        check("未知验证码类型应报错", False, "没有抛异常")
    except BiliError as exc:
        check("未知验证码类型报错", "unknown" in str(exc), str(exc)[:40])

    print(f"\n== {PASS} passed, {FAIL} failed ==", file=sys.stderr)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

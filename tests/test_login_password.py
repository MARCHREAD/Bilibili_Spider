"""密码登录编排的离线验证（**零网络请求**）。

背景（本机实测，见 tests/captcha_ttl.py）
----------------------------------------
passport 下发的 gt/challenge/token 约 120 秒后失效；登录端**先验验证码、后验账号
密码**（不带验证码字段时直接 -105）。所以"提交晚了"必然表现为 -105/-662，
而 -400/-629 才是账号密码层的判决。

本测试用假 client + 假解算器覆盖 login_password 的全部决策分支：
  * 预算内的预取→解算→提交链路；
  * 解算失败 / 解算超预算：不提交，换新 challenge 重来；
  * -105/-662：重新预取重解重提（有界）；
  * -400/-629：立即返回，不做无意义重试；
  * recaptcha_* 旧 schema 归一化、服务端不派 geetest 的情形。

用法：python tests/test_login_password.py
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import time
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb import gt3
from biliwb import accounts as accounts_mod
from biliwb.accounts import AccountPool
from biliwb.store import Store

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


class FakeClient:
    """只实现 login_password 用到的会话表面。"""

    def __init__(self, captcha_body: dict, login_replies: list[dict]) -> None:
        self.captcha_body = captcha_body
        self.login_replies = list(login_replies)
        self.urls: list[str] = []
        self.sent_logins: list[dict] = []

    # 会话引导：全部空操作
    def bootstrap(self): return {}
    def warmup(self): return None
    def gen_ticket(self): return None
    def cookie_dict(self): return {}
    def export_cookies(self): return "SESSDATA=test"
    def nav(self, refresh: bool = False):
        return {"isLogin": True, "mid": 42, "uname": "tester", "face": ""}

    def request_json(self, url: str, **kw):
        self.urls.append(url)
        if "passport-login/captcha" in url:
            return self.captcha_body
        if url.endswith("/web/key"):
            return {"code": 0, "data": {"key": "PUBKEY", "hash": "SALT"}}
        if url.endswith("/web/login"):
            if not self.login_replies:
                raise AssertionError("多余的一次 /web/login 提交")
            return self.login_replies.pop(0)
        raise AssertionError(f"未预期的请求: {url}")


def init_body(schema: str = "legacy", token: str = "TOK1", idx: int = 1) -> dict:
    if schema == "recaptcha":
        return {"code": 0, "data": {"recaptcha_type": "geetest",
                                    "recaptcha_token": token,
                                    "gee_gt": "GT", "gee_challenge": f"CH{idx}"}}
    if schema == "img":
        return {"code": 0, "data": {"type": "img", "token": token}}
    return {"code": 0, "data": {"type": "geetest", "token": token,
                                "geetest": {"gt": "GT", "challenge": f"CH{idx}"}}}


def solve_reply(ok: bool = True, seconds: float = 16.0, idx: int = 1, error: str | None = None):
    if not ok:
        return {"ok": False, "seconds": seconds, "error": error or "未取得 validate（求解失败）",
                "verdict": '{"status": "error", "error_code": "error_51"}',
                "log_tail": ["[verdict] ajax.php -> error_51"], "http_used": 11}
    return {"ok": True, "gt": "GT", "challenge": f"CH{idx}", "token": f"TOK{idx}",
            "validate": f"VAL{idx}", "seccode": f"VAL{idx}|jordan", "score": "14",
            "seconds": seconds, "http_used": 11}


def run_scenario(solve_script, login_script, *, attempts=2, budget=75,
                 schema="legacy", captcha_bodies=None):
    """跑一次 login_password，返回 (result, 计数, solve 收到的参数列表)。"""
    tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
    store = Store(pathlib.Path(tmp.name) / "t.db")
    pool = AccountPool(store, data_dir=tmp.name)
    aid = store.create_account("t", login_method="password", username="13800000000",
                               password_enc=pool.box.protect("pw123456"))

    bodies = list(captcha_bodies) if captcha_bodies else None
    cli = FakeClient(bodies.pop(0) if bodies else init_body(schema), list(login_script))
    counts = {"prefetch": 0, "solve": 0, "submit": 0}
    solve_args: list[dict] = []

    real_prefetch = pool._captcha_prefetch

    def prefetch(client, source):
        counts["prefetch"] += 1
        if bodies:
            cli.captcha_body = bodies.pop(0)
        return real_prefetch(client, source)

    def fake_solve(**kw):
        counts["solve"] += 1
        solve_args.append(kw)
        item = solve_script[min(counts["solve"] - 1, len(solve_script) - 1)]
        return item(counts["solve"]) if callable(item) else item

    real_request = cli.request_json

    def counting_request(url, **kw):
        if url.endswith("/web/login"):
            counts["submit"] += 1
            cli.sent_logins.append(dict(kw.get("data") or {}))
        return real_request(url, **kw)

    with mock.patch.object(accounts_mod.gt3, "solve_once", fake_solve), \
         mock.patch.object(accounts_mod, "rsa_encrypt", lambda k, p: "ENC"), \
         mock.patch.object(pool, "client", lambda aid: cli), \
         mock.patch.object(pool, "_captcha_prefetch", prefetch), \
         mock.patch.object(cli, "request_json", counting_request):
        result = pool.login_password(aid, attempts=attempts, gt3_timeout=budget)
    store.close()
    tmp.cleanup()
    return result, counts, solve_args, cli.sent_logins


def ok_reply(idx_note: str = "") -> dict:
    return {"code": 0, "message": "0", "data": {"status": 0, "url": "",
                                               "refresh_token": "rt", "timestamp": 1}}


def main() -> int:
    print("== 密码登录编排（离线）==", file=sys.stderr)

    # 1. 一次通过
    res, n, args, sent = run_scenario([solve_reply(seconds=16)], [ok_reply()])
    check("一次通过", res.get("ok") is True and res.get("stage") == "done"
          and (n["prefetch"], n["solve"], n["submit"]) == (1, 1, 1),
          f"counts={n} code={res.get('code')}")
    check("预算作为解算超时下发", args and args[0].get("timeout") == 75, f"timeout={args[0].get('timeout') if args else None}")
    check("提交带上了本轮 validate/challenge/token",
          sent and sent[0].get("validate") == "VAL1"
          and sent[0].get("challenge") == "CH1"
          and sent[0].get("seccode") == "VAL1|jordan"
          and sent[0].get("token") == "TOK1",
          f"sent={ {k: sent[0].get(k) for k in ('validate','challenge','seccode','token')} if sent else None }")

    # 2. 解算失败一次 -> 自动换 challenge 重来
    res, n, _, sent = run_scenario([solve_reply(ok=False), solve_reply(seconds=16)],
                             [ok_reply()])
    check("解算失败自动重取重解", res.get("ok") is True
          and (n["prefetch"], n["solve"], n["submit"]) == (2, 2, 1), f"counts={n}")
    check("失败原因（极验判决）被回传",
          "error_51" in json.dumps(res.get("attempt_history"), ensure_ascii=False),
          "verdict 在 attempt_history 里")

    # 3. 解算超预算 -> 不提交，重来
    res, n, _, sent = run_scenario([solve_reply(seconds=95), solve_reply(seconds=16)],
                             [ok_reply()])
    check("超预算不提交并重来", res.get("ok") is True
          and (n["prefetch"], n["solve"], n["submit"]) == (2, 2, 1), f"counts={n}")

    # 4. -105（验证码不被接受）-> 重取重解重提
    res, n, _, sent = run_scenario([solve_reply(seconds=16), solve_reply(seconds=16, idx=2)],
                             [{"code": -105, "message": "验证码错误"}, ok_reply()])
    check("-105 自动重来并成功", res.get("ok") is True
          and (n["prefetch"], n["solve"], n["submit"]) == (2, 2, 2), f"counts={n}")
    check("token 年龄被记录", isinstance(res.get("token_age"), (int, float)),
          f"token_age={res.get('token_age')}")

    # 5. -662（已过期）同样触发重试
    res, n, _, sent = run_scenario([solve_reply(seconds=16), solve_reply(seconds=16, idx=2)],
                             [{"code": -662, "message": "验证码已过期"}, ok_reply()])
    check("-662 自动重来并成功", res.get("ok") is True
          and (n["prefetch"], n["submit"]) == (2, 2), f"counts={n}")

    # 6. -400 账号密码错 -> 不重试
    res, n, _, sent = run_scenario([solve_reply(seconds=16)],
                             [{"code": -400, "message": "用户名或密码错误"}])
    check("-400 立即返回不重试", res.get("ok") is False and res.get("stage") == "rejected"
          and (n["prefetch"], n["submit"]) == (1, 1),
          f"counts={n} hint={res.get('hint')}")

    # 7. -629 次数过多 -> 不重试，并给出可操作提示
    res, n, _, sent = run_scenario([solve_reply(seconds=16)],
                             [{"code": -629, "message": "用户名或密码错误次数过多"}])
    check("-629 立即返回不重试", res.get("ok") is False and res.get("stage") == "rejected"
          and (n["prefetch"], n["submit"]) == (1, 1), f"counts={n}")
    check("-629 提示可读", "次数过多" in (res.get("hint") or ""), res.get("hint"))

    # 8. 连续被验证码拒绝 -> 用尽次数后报明确错误
    res, n, _, sent = run_scenario([solve_reply(seconds=16), solve_reply(seconds=16, idx=2)],
                             [{"code": -105, "message": "验证码错误"},
                              {"code": -105, "message": "验证码错误"}], attempts=2)
    check("连续 -105 用尽次数后有明确说明",
          res.get("ok") is False and "连续" in (res.get("error") or "")
          and (n["prefetch"], n["submit"]) == (2, 2), f"err={res.get('error')}")

    # 9. recaptcha_* 旧 schema 归一化
    res, n, args, sent = run_scenario([solve_reply(seconds=16)], [ok_reply()], schema="recaptcha")
    check("recaptcha_* schema 归一化", res.get("ok") is True
          and args and args[0].get("challenge") == "CH1"
          and args[0].get("gt") == "GT" and args[0].get("token") == "TOK1",
          f"solve_args={ {k: v for k, v in (args[0] if args else {}).items() if k in ('gt','challenge','token')} }")

    # 10. 服务端不派 geetest（例如图形验证码通道）
    res, n, _, sent = run_scenario([solve_reply(seconds=16)], [ok_reply()], schema="img")
    check("未派 geetest 时不空跑解算器", res.get("ok") is False
          and n["solve"] == 0 and "geetest" in (res.get("error") or ""),
          f"counts={n} err={res.get('error')}")

    # 11. 预取在同一个 client 会话上发生（而不是解算器自己那套匿名会话）
    res, n, args, sent = run_scenario([solve_reply(seconds=16)], [ok_reply()])
    check("解算使用会话预取的 gt/challenge/token",
          args and args[0].get("gt") == "GT" and args[0].get("challenge") == "CH1",
          "预取→解算同源")

    # 12. code=0 但 status!=0：服务端要求 /riskVerify 人工安全验证
    #     （实测语义：chunk 409 的 riskVerify 走 x/safecenter 短信/邮箱验证码，
    #      通过后再用 x/passport-login/web/exchange_cookie 换登录态）
    risk_url = "https://passport.bilibili.com/riskVerify?tmp_token=abc123"
    res, n, _, _ = run_scenario([solve_reply(seconds=16)],
                                [{"code": 0, "message": "0",
                                  "data": {"status": 1, "url": risk_url}}])
    check("status!=0 -> challenge", res.get("ok") is False
          and res.get("stage") == "challenge", f"stage={res.get('stage')}")
    check("challenge 把 status 暴露出来", res.get("status") == 1, f"status={res.get('status')}")
    check("challenge 把验证地址暴露出来（旧实现丢掉了）",
          res.get("challenge_url") == risk_url and "riskVerify" in (res.get("challenge_url") or ""),
          f"url={res.get('challenge_url')}")
    check("challenge 提示指向人工验证/扫码",
          "验证" in (res.get("hint") or ""), (res.get("hint") or "")[:40])

    print(f"\n== {PASS} passed, {FAIL} failed ==", file=sys.stderr)
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

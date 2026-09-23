"""status=2 风控二次验证（短信校验绑定手机号）的**半自动**协议实现。

这不是"绕过"：短信验证码发到用户绑定的手机，必须由用户本人读出来交给我们。
本模块只把"能自动化的部分"自动化（预取验证码、过极验/图形验证码、发短信、
换 cookie），把"必须人做的部分"（读短信）留给用户。

流程与参数全部挖自官方前端（只读抓取，见 tests/mine_risk_flow.py）：
  passport PC chunk 409/86 的模块 9207（/riskVerify 组件 risk-check-phone）
  passport H5 chunk 9212（/risk/verify 组件 loginRisk）

    POST /x/safecenter/captcha/pre            -> {type, token, geetest:{gt,challenge}} / img
    过验证码（geetest 用本仓库的 GT3 解算器；img 用 ddddocr）
    POST /x/safecenter/common/sms/send        {tmp_code, sms_type, recaptcha_token, gee_*|img_code}
        -> data.captcha_key                         ← 用户手机此时收到短信
    POST /x/safecenter/login/tel/verify       {tmp_code, captcha_key, type, code, request_id, source}
        -> data.code
    POST /x/passport-login/web/exchange_cookie {source, code, go_url}
        -> Set-Cookie（登录态落到会话）
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
import urllib.parse

from . import constants as C
from .client import BiliClient
from .errors import BiliError

# 三种校验分支由 URL 的 scene 决定；我们的 status=2 url 没有 scene -> 默认 loginTelCheck
SMS_TYPE_DEFAULT = "loginTelCheck"
EP_CAPTCHA_PRE = f"{C.PASSPORT}/x/safecenter/captcha/pre"
EP_SMS_SEND = f"{C.PASSPORT}/x/safecenter/common/sms/send"
EP_TEL_VERIFY = f"{C.PASSPORT}/x/safecenter/login/tel/verify"
EP_DEVICE_VERIFY = f"{C.PASSPORT}/x/safecenter/user_device/verify"
EP_SEC_VERIFY = f"{C.PASSPORT}/x/safecenter/sec/verify"
EP_EXCHANGE = f"{C.PASSPORT}/x/passport-login/web/exchange_cookie"


def parse_challenge_url(url: str) -> dict:
    """从 status!=0 返回的 url 里取出 tmp_token / request_id / source / gourl。"""
    if not url:
        return {}
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query, keep_blank_values=True)

    def one(key: str, default=None):
        v = q.get(key)
        return v[0] if v and v[0] else default

    return {
        "url": url,
        "tmp_token": one("tmp_token"),
        "request_id": one("request_id"),
        "source": one("source", "risk"),
        "gourl": one("gourl", C.WWW + "/"),
        "scene": one("scene"),
    }


def sms_type_of(ctx: dict) -> str:
    return ctx.get("scene") or SMS_TYPE_DEFAULT


# --------------------------------------------------------------- 步骤 1/2：验证码

def captcha_pre(client: BiliClient, ctx: dict) -> dict:
    """预取发短信所需的人机验证码（极验或图形）。"""
    body = client.request_json(EP_CAPTCHA_PRE, method="POST", data={},
                               soft=True, retries=1,
                               headers={"Referer": ctx.get("url") or C.PASSPORT})
    data = (body or {}).get("data") or {}
    if (body or {}).get("code") != 0:
        raise BiliError(f"验证码预取失败: {(body or {}).get('message')}", 
                        (body or {}).get("code"), EP_CAPTCHA_PRE)
    if data.get("recaptcha_type"):
        data = {"type": data.get("recaptcha_type"), "token": data.get("recaptcha_token"),
                "geetest": {"gt": data.get("gee_gt"), "challenge": data.get("gee_challenge")}}
    return data


def solve_captcha(client: BiliClient, pre: dict, timeout: int = 75) -> dict:
    """过掉 pre 返回的验证码，返回可并入发短信请求的字段。"""
    ctype = pre.get("type")
    token = pre.get("token")
    fields: dict = {"recaptcha_token": token}
    if ctype == "geetest":
        gee = pre.get("geetest") or {}
        from . import gt3
        cap = gt3.solve_once(gt=gee.get("gt"), challenge=gee.get("challenge"),
                             token=token, timeout=timeout)
        if not cap.get("ok"):
            raise BiliError(f"过人机验证码失败: {cap.get('error')}", url=EP_CAPTCHA_PRE)
        fields.update({"gee_challenge": cap["challenge"], "gee_seccode": cap["seccode"],
                       "gee_validate": cap["validate"]})
        fields["_solve"] = {"seconds": cap.get("seconds"), "score": cap.get("score")}
        return fields
    if ctype == "img":
        # 图形验证码：GET /x/recaptcha/img?token=<token>，ddddocr 识别
        url = f"{C.API}/x/recaptcha/img?_={int(time.time() * 1000)}&token={token}"
        raw = client._raw("GET", url).content
        code = _ocr_img(raw)
        if not code:
            raise BiliError("图形验证码识别失败", url=url)
        fields.update({"img_code": code})
        fields["_solve"] = {"img_code_len": len(code)}
        return fields
    raise BiliError(f"未知的验证码类型: {ctype}", url=EP_CAPTCHA_PRE)


def _ocr_img(raw: bytes) -> str | None:
    """本地 ddddocr 识别 5 位图形验证码（b 站 recaptcha img 是 5 位字母数字）。"""
    try:
        import ddddocr
    except Exception:  # noqa: BLE001
        return None
    try:
        return ddddocr.DdddOcr(show_ad=False).classification(raw) or None
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------- 步骤 3：发短信

def send_sms(client: BiliClient, ctx: dict, captcha_fields: dict) -> dict:
    """发短信；返回 {captcha_key, raw}。用户手机会收到验证码。"""
    payload = {
        "tmp_code": ctx.get("tmp_token"),
        "sms_type": sms_type_of(ctx),
        "recaptcha_token": captcha_fields.get("recaptcha_token"),
    }
    for k in ("gee_challenge", "gee_seccode", "gee_validate", "img_code"):
        if captcha_fields.get(k):
            payload[k] = captcha_fields[k]
    body = client.request_json(EP_SMS_SEND, method="POST", data=payload,
                               soft=True, retries=1,
                               headers={"Referer": ctx.get("url") or C.PASSPORT})
    code = int((body or {}).get("code", -1))
    data = (body or {}).get("data") or {}
    if code != 0:
        raise BiliError(f"发送短信失败: {(body or {}).get('message')}", code, EP_SMS_SEND)
    return {"captcha_key": data.get("captcha_key"), "raw": data}


# --------------------------------------------------------------- 步骤 4：校验短信

def verify_sms(client: BiliClient, ctx: dict, captcha_key: str, code: str) -> str:
    """提交用户收到的短信验证码，返回 exchange_cookie 需要的 code。"""
    sms_type = sms_type_of(ctx)
    if sms_type == "secLogin":
        ep, payload = EP_SEC_VERIFY, {"verify_type": "sms", "tmp_code": ctx.get("tmp_token"),
                                      "captcha_key": captcha_key, "code": code}
    elif sms_type == "deviceVerify":
        ep, payload = EP_DEVICE_VERIFY, {"tmp_code": ctx.get("tmp_token"), "code": code,
                                        "sms_type": sms_type, "captcha_key": captcha_key}
    else:  # loginTelCheck（我们的 status=2 url 没有 scene，走这条）
        ep, payload = EP_TEL_VERIFY, {"tmp_code": ctx.get("tmp_token"), "captcha_key": captcha_key,
                                      "type": sms_type, "code": code}
        if ctx.get("request_id"):
            payload["request_id"] = ctx["request_id"]
        if ctx.get("source"):
            payload["source"] = ctx["source"]
    body = client.request_json(ep, method="POST", data=payload, soft=True, retries=1,
                               headers={"Referer": ctx.get("url") or C.PASSPORT})
    rcode = int((body or {}).get("code", -1))
    if rcode != 0:
        raise BiliError(f"短信验证失败: {(body or {}).get('message')}", rcode, ep)
    data = (body or {}).get("data") or {}
    ticket = data.get("code") if isinstance(data, dict) else data
    if not ticket:
        raise BiliError("短信验证通过但未拿到 exchange code", rcode, ep)
    return str(ticket)


# --------------------------------------------------------------- 步骤 5：换 cookie

def exchange_cookie(client: BiliClient, ctx: dict, ticket: str) -> dict:
    """用校验得到的 code 换登录 cookie（cookie 落在该 client 的会话上）。"""
    payload = {"source": ctx.get("source") or "main_web", "code": ticket,
               "go_url": ctx.get("gourl") or (C.WWW + "/")}
    resp = client._raw("POST", EP_EXCHANGE, data=payload,
                       headers={"Referer": ctx.get("url") or C.PASSPORT})
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {"raw": resp.text[:200]}
    cookies = client.cookie_dict()
    ok = bool(cookies.get("SESSDATA"))
    return {"ok": ok, "code": (body or {}).get("code"), "message": (body or {}).get("message"),
            "has_sessdata": ok, "http": resp.status_code,
            "data": {k: v for k, v in ((body or {}).get("data") or {}).items()
                     if k in ("status", "url", "mid", "timestamp")} if isinstance(body, dict) else {}}

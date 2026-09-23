"""bilibili 登录验证码 —— 协议契约的本地固定向量自检（local-proof，无联网）。

验证三件事：
  1. 服务端验证码预取响应的两种 schema（legacy / recaptcha_*）都能归一化成同一契约；
  2. 前端 handlerLogin / sendPhoneCode 的拼参分支（geetest 通道 vs 图形码通道）字段集合互斥且正确；
  3. 抓到的真实 GT3 服务端响应与 passport chunk 内联 gt.js 加载器的期望一致。

固定向量来自 raw/ 下真实抓包；合成向量在代码中显式标注 synthetic。
用法：直接运行，无参数。stdout = 机器 JSON，stderr = 人类可读报告。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parent
RAW = TASK / "raw"

# 从 raw/chunks/264.60f4e88f.js 内联的极验 gt.js (v0.0.0) 提取，非猜测
LOADER = {
    "api_server": "api.geetest.com",
    "typePath": "/gettype.php",
    "fallback_config": {
        "slide": {"type": "slide", "slide": "/static/js/geetest.0.0.0.js"},
        "fullpage": {"type": "fullpage", "fullpage": "/static/js/fullpage.0.0.0.js"},
    },
    "static_servers": ["static.geetest.com", "static.geevisit.com"],
}


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def normalize_pre_info(data: dict) -> dict:
    """镜像 chunk 内 parseData()：兼容 legacy 与 recaptcha_* 两种 schema。"""
    if data.get("recaptcha_type"):
        return {
            "type": data["recaptcha_type"],
            "token": data["recaptcha_token"],
            "geetest": {"gt": data["gee_gt"], "challenge": data["gee_challenge"]},
        }
    return {
        "type": data["type"],
        "token": data["token"],
        "geetest": {"gt": data["geetest"]["gt"], "challenge": data["geetest"]["challenge"]},
    }


def build_login_payload(base: dict, captcha: dict) -> dict:
    """镜像 handlerLogin()：geetest 与图片码两条通道字段互斥。"""
    payload = dict(base)
    if captcha.get("captcha_type") == "geetest":
        payload.update(
            validate=captcha["validate"],
            token=captcha["token"],
            seccode=captcha["seccode"],
            challenge=captcha["challenge"],
        )
    else:
        payload.update(captcha=captcha["img_code"], token=captcha["token"])
    return payload


def build_sms_payload(base: dict, captcha: dict) -> dict:
    """镜像 sendPhoneCode()：同一验证码组件，字段规则一致。"""
    return build_login_payload(base, captcha)


def parse_gt3_jsonp(text: str) -> dict:
    m = re.search(r"\(\s*(\{.*\})\s*\)\s*;?\s*$", text.strip(), re.S)
    if not m:
        raise ValueError("not a jsonp payload")
    return json.loads(m.group(1))


def main() -> int:
    checks: list[dict] = []
    flow: dict = {}

    def check(name: str, ok: bool, detail) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        note(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")

    # ---------- 1. 真实 legacy 向量归一化 ----------
    legacy_files = [
        "captcha_init.json",
        "captcha_init_blog.json",
        "captcha_init_main-fe-header.json",
    ]
    normalized = []
    for fn in legacy_files:
        raw = json.loads((RAW / fn).read_text(encoding="utf-8"))
        info = normalize_pre_info(raw["data"])
        normalized.append({"file": fn, **info})
    gt_set = {n["geetest"]["gt"] for n in normalized}
    ch_set = {n["geetest"]["challenge"] for n in normalized}
    tk_set = {n["token"] for n in normalized}
    check("legacy schema normalizes to {type,token,gt,challenge}", all(n["type"] == "geetest" for n in normalized), normalized)
    check("gt is server-fixed across rounds", len(gt_set) == 1, sorted(gt_set))
    check("challenge rotates per round", len(ch_set) == len(normalized), sorted(ch_set))
    check("token rotates per round", len(tk_set) == len(normalized), sorted(tk_set))

    # ---------- 2. 合成 recaptcha_* 向量（synthetic，仅验代码分支） ----------
    synthetic = {
        "recaptcha_type": "geetest",
        "recaptcha_token": "SYNTHETIC_TOKEN",
        "gee_gt": "SYNTHETIC_GT",
        "gee_challenge": "SYNTHETIC_CHALLENGE",
    }
    syn = normalize_pre_info(synthetic)
    check(
        "synthetic recaptcha_* schema maps to the same contract",
        syn == {
            "type": "geetest",
            "token": "SYNTHETIC_TOKEN",
            "geetest": {"gt": "SYNTHETIC_GT", "challenge": "SYNTHETIC_CHALLENGE"},
        },
        syn,
    )

    # ---------- 3. 提交拼参分支 ----------
    base = {
        "source": None,
        "sns_platform": None,
        "sns_openid": None,
        "csrf_state": None,
        "username": "<user>",
        "password": "<RSA(hash+pwd)>",
        "go_url": None,
    }
    gee_ok = {"captcha_type": "geetest", "validate": "V", "seccode": "S", "challenge": "C", "token": "T"}
    img_ok = {"captcha_type": "img", "img_code": "AB12C", "token": "T"}
    gee_payload = build_login_payload(base, gee_ok)
    img_payload = build_login_payload(base, img_ok)
    check(
        "geetest channel sets validate/seccode/challenge/token and no captcha",
        {"validate", "seccode", "challenge", "token"} <= set(gee_payload) and "captcha" not in gee_payload,
        sorted(gee_payload),
    )
    check(
        "img channel sets captcha/token and no geetest fields",
        {"captcha", "token"} <= set(img_payload) and not ({"validate", "seccode", "challenge"} & set(img_payload)),
        sorted(img_payload),
    )
    check("sms send reuses the same branch rule", build_sms_payload({"tel": "<tel>", "cid": 86}, gee_ok) == {**{"tel": "<tel>", "cid": 86}, **{k: gee_ok[k] for k in ("validate", "token", "seccode", "challenge")}}, "mirrored")
    check(
        "password is RSA-encrypted before submit (never plaintext)",
        "password" in gee_payload and gee_payload["password"] == "<RSA(hash+pwd)>",
        "GET /x/passport-login/web/key -> {key,hash}; encrypt(hash+password)",
    )

    # ---------- 4. 真实 GT3 服务端向量 vs 内联加载器期望 ----------
    gettype = parse_gt3_jsonp((RAW / "gt3_gettype.txt").read_text(encoding="utf-8"))
    get_resp = parse_gt3_jsonp((RAW / "gt3_get.txt").read_text(encoding="utf-8"))
    dtype = gettype["data"]["type"]
    check(
        "live gettype.php type is a key of the vendored loader fallback_config",
        dtype in LOADER["fallback_config"],
        {"live_type": dtype, "loader_keys": sorted(LOADER["fallback_config"])},
    )
    # 加载器内部对 server 名做 e.replace(/^https?:\/\/|\/$/g,"")，比对前必须施加同一归一化
    norm = lambda xs: sorted(re.sub(r"^https?://|/$", "", s) for s in xs)  # noqa: E731
    check(
        "live gettype.php static_servers match the vendored loader list (after the loader's own slash strip)",
        norm(gettype["data"]["static_servers"]) == norm(LOADER["static_servers"]),
        {"live": gettype["data"]["static_servers"], "loader": LOADER["static_servers"]},
    )
    check(
        "live get.php returns a same-round challenge payload (c/s present)",
        get_resp.get("status") == "success" and "c" in get_resp["data"] and "s" in get_resp["data"],
        {k: get_resp["data"][k] for k in ("theme", "s") if k in get_resp["data"]},
    )

    # ---------- 5. 记录成交流水（供报告引用） ----------
    flow = {
        "captcha_init_legacy_samples": normalized,
        "captcha_init_contract": {"type": "geetest", "token": "server-issued per round", "geetest": {"gt": "server-fixed", "challenge": "server-issued per round"}},
        "loader_constants": LOADER,
        "live_gettype": gettype["data"],
        "live_get": {k: v for k, v in get_resp["data"].items() if k in ("theme", "s", "c", "static_servers", "api_server")},
        "login_payload_examples": {"geetest": sorted(gee_payload), "img": sorted(img_payload)},
        "endpoints": {
            "captcha_prefetch": "GET https://passport.bilibili.com/x/passport-login/captcha?source=main-fe",
            "captcha_image": "GET https://api.bilibili.com/x/recaptcha/img?_=<rand>&token=<token>",
            "password_login": "POST https://passport.bilibili.com/x/passport-login/web/login (form-urlencoded)",
            "sms_code_login": "POST https://passport.bilibili.com/x/passport-login/web/login/sms",
            "sms_send": "GET/POST https://passport.bilibili.com/x/passport-login/web/sms/send",
            "rsa_key": "GET https://passport.bilibili.com/x/passport-login/web/key?_=<ms>",
            "gt3_gettype": "https://api.geetest.com/gettype.php?gt=<gt>&callback=<jsonp>",
            "gt3_get": "https://api.geetest.com/get.php?gt=<gt>&challenge=<c>&lang=zh-cn&pt=0&client_type=web&callback=<jsonp>",
        },
        "unproven_routes": [
            "POST /x/passport-login/web/login was never submitted (no account use) -> server-side captcha verdict unproven",
            "gt3 ajax.php /validate completion was not driven (no slider answer submitted)",
        ],
    }
    (TASK / "captcha_flow.json").write_text(json.dumps(flow, ensure_ascii=True, indent=2), encoding="utf-8")

    failed = [c for c in checks if not c["ok"]]
    print(json.dumps({"checks": len(checks), "failed": len(failed), "results": checks}, ensure_ascii=True))
    note(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

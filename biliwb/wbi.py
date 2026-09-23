"""WBI 签名（纯 Python，无浏览器、无 JS helper）。

协议形状（live 报文实测）：

    GET https://api.bilibili.com/x/player/wbi/v2?aid=..&cid=..&w_rid=<32hex>&wts=<秒>

签名算法：

    mixin_key = (img_key + sub_key)[MIXIN_KEY_ENC_TAB] 取前 32 位
    query     = 除 w_rid/wts 外的参数按 key 升序，"!"'()*" 从值中剔除后
                percent-encode（规则等价 encodeURIComponent）并以 & 连接
    w_rid     = md5(query + "&wts=" + wts + mixin_key)   # wts 参与并排在最后

注意：wts 是参与签名的普通参数（排序后按 key 归位），不是 append 在末尾。
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.parse

from .constants import MIXIN_KEY_ENC_TAB

_STRIP = re.compile(r"[!'()*]")


def get_mixin_key(orig: str) -> str:
    """按混淆表重排 img_key+sub_key 并取前 32 位。"""
    return "".join(orig[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def _enc(value: object) -> str:
    """等价于 JS encodeURIComponent（quote 的 always-safe 集合已含 _.-~）。"""
    return urllib.parse.quote(str(value), safe="")


def encode_query(params: dict) -> str:
    """按 WBI 规则生成待签名 query，保证 encode 与 sort 顺序一致。"""
    parts = []
    for key in sorted(params):
        value = _STRIP.sub("", str(params[key]))
        parts.append(f"{_enc(key)}={_enc(value)}")
    return "&".join(parts)


def sign(params: dict, img_key: str, sub_key: str, wts: int | None = None) -> dict:
    """返回带 w_rid / wts 的新参数字典（不修改入参）。"""
    payload = {k: v for k, v in params.items() if k not in ("w_rid", "wts")}
    payload["wts"] = int(time.time()) if wts is None else int(wts)
    query = encode_query(payload)
    w_rid = hashlib.md5((query + get_mixin_key(img_key + sub_key)).encode()).hexdigest()
    signed = dict(payload)
    signed["w_rid"] = w_rid
    return signed


def keys_from_nav(nav_data: dict) -> tuple[str, str]:
    """从 /x/web-interface/nav 的 data.wbi_img 提取 (img_key, sub_key)。"""
    wbi_img = (nav_data or {}).get("wbi_img") or {}
    img = str(wbi_img.get("img_url", "")).rsplit("/", 1)[-1].split(".")[0]
    sub = str(wbi_img.get("sub_url", "")).rsplit("/", 1)[-1].split(".")[0]
    if not img or not sub:
        raise ValueError("nav 响应缺少 wbi_img.img_url / sub_url")
    return img, sub


def parse_query(url: str) -> dict:
    """把一个完整 URL 的 query 解析为普通字典（用于离线 fixed-vector 校验）。"""
    query = url.split("?", 1)[1] if "?" in url else ""
    out: dict[str, str] = {}
    for pair in query.split("&"):
        if not pair:
            continue
        key, _, value = pair.partition("=")
        out[urllib.parse.unquote(key)] = urllib.parse.unquote(value)
    return out


def verify_vector(url: str, img_key: str, sub_key: str) -> tuple[bool, str]:
    """对一条真实抓包 URL 复算 w_rid，返回 (是否一致, 复算值)。"""
    params = parse_query(url)
    expect = params.get("w_rid", "")
    got = sign(params, img_key, sub_key, wts=int(params.get("wts", 0)))["w_rid"]
    return got == expect, got

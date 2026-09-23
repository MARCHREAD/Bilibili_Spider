"""HTTP 客户端：cookie 会话 + 引导（buvid/ticket）+ WBI 签名 + 限速重试。

设计原则
--------
* 传输身份锁定为本地 curl_cffi 实际最大 chrome 版本（见 constants.IMPERSONATE），
  不套用 live 浏览器更新的大版本。
* 一切业务 HTTP 由 Python 拥有；无浏览器、无 CDP、无页面驱动。
* 风控（HTTP 412 / code -352）显式识别并退避，不伪装成"外部故障"。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import threading
import time
from typing import Any

from curl_cffi import requests as cffi

from . import constants as C
from . import wbi as wbi_mod
from .errors import (BiliError, NotLoggedIn, RiskControl, SoftRisk, TransportError,
                     raise_for_code)

# 浏览器侧的默认请求头（不含 UA —— UA 由 impersonate 提供，避免版本漂移）
BASE_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Origin": C.WWW,
    "Referer": C.WWW + "/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    # 实测：不加 no-cache 时同一 URL 会拿到 HTTP 304（弹幕二进制接口尤其明显）
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

TICKET_HMAC_KEY = b"XgwSnGZ1p"
TICKET_KEY_ID = "ec02"


def gaia_slots() -> dict:
    """gaia 指纹槽位。

    实测（one-variable ablation）：`space/wbi/acc/info` 不带这组参数返回 -352，
    带上后 code=0；Referer/Origin 不是决定性变量。
    这些值取自 live 样本，作为**显式配置输入**，运行时不再读浏览器。
    """
    return {
        "dm_img_list": "[]",
        "dm_img_str": C.GAIA_DM_IMG_STR,
        "dm_cover_img_str": C.GAIA_DM_COVER_IMG_STR,
        "dm_img_inter": C.GAIA_DM_IMG_INTER,
    }



def soft_risk_hit(body: dict | None) -> bool:
    """是否是**软风控**响应：HTTP 200 + code 0，但业务载荷被 `v_voucher` 顶掉。

    旧实现要求 `data` **恰好只有一个键**且是 `v_voucher`，一旦接口返回的是
    `{"replies": [], "cursor": {...}, "v_voucher": ...}` 这种带分页元信息的多键形态，
    就检测不到 —— 分页循环会把它当成"已到末页"而**静默截断数据**。
    因此这里只认标志位本身（`v_voucher` 是 gaia 的占位符，正常业务响应不会携带）。
    """
    if not isinstance(body, dict):
        return False
    data = body.get("data")
    if isinstance(data, dict) and "v_voucher" in data:
        return True
    return "v_voucher" in body


def _rand_lsid() -> str:
    return "%08X_%08X" % (random.getrandbits(32), random.getrandbits(32) | 0x10000000)


def _rand_uuid() -> str:
    rnd = "".join(random.choice("0123456789ABCDEF") for _ in range(8))
    return f"{rnd[:8]}-{rnd[8:12]}-{rnd[12:16]}-{rnd[16:20]}-{rnd[20:32]}infoc"


class BiliClient:
    """带会话与限速的 bilibili HTTP 客户端。"""

    def __init__(
        self,
        cookie_file: str | None = None,
        impersonate: str = C.IMPERSONATE,
        min_delay: float = 1.0,
        jitter: float = 0.4,
        timeout: float = 20.0,
        retries: int = 3,
        soft_risk_retries: int = 10,
        verbose: bool = False,
    ) -> None:
        self.impersonate = impersonate
        self.min_delay = float(min_delay)
        self.jitter = float(jitter)
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.soft_risk_retries = int(soft_risk_retries)
        self.verbose = verbose

        self.cookie_file = cookie_file
        self._lock = threading.Lock()
        self._last_call = 0.0
        self._wbi_keys: tuple[str, str] | None = None
        self._nav_cache: dict | None = None
        self.http_calls = 0
        self._recovering = False          # 软风控自愈的可重入保护
        # 可选的持久化 midHash 字典（由 server 注入；见 store.MidHashIndex）
        self.midhash_index = None

        self.session = cffi.Session(impersonate=impersonate)
        self.session.headers.update(BASE_HEADERS)
        if cookie_file:
            self.load_cookies(cookie_file)

    # ------------------------------------------------------------ 日志

    def _log(self, *parts: object) -> None:
        # 关键请求/响应摘要一律走 stderr，stdout 留给机器可读 JSON
        if self.verbose:
            print("[biliwb]", *parts, file=__import__("sys").stderr)

    # ------------------------------------------------------------ 会话持久化

    def cookie_dict(self) -> dict[str, str]:
        out: dict[str, str] = {}
        try:
            for c in self.session.cookies.jar:
                out[c.name] = c.value
        except Exception:
            for k, v in dict(self.session.cookies).items():
                out[k] = v
        return out

    def export_cookies(self) -> str:
        """导出为 Netscape/请求头兼容的 `k=v; k=v` 串。"""
        return "; ".join(f"{k}={v}" for k, v in self.cookie_dict().items())

    def import_cookies(self, raw: str) -> int:
        """从 `k=v; k=v` 串或 Cookie 编辑器的 JSON 导入，返回导入条数。"""
        pairs = self._parse_cookie_input(raw)
        for key, value in pairs.items():
            self._set_cookie(key, value)
        self._wbi_keys = None
        self._nav_cache = None
        return len(pairs)

    @staticmethod
    def _parse_cookie_input(raw: str) -> dict[str, str]:
        text = (raw or "").strip()
        if not text:
            return {}
        if text.startswith("[") or text.startswith("{"):
            try:
                data = json.loads(text)
                items = data if isinstance(data, list) else data.get("cookies", [])
                return {
                    str(it["name"]): str(it["value"])
                    for it in items
                    if isinstance(it, dict) and it.get("name")
                }
            except Exception:
                pass
        pairs: dict[str, str] = {}
        for chunk in text.replace("\n", ";").split(";"):
            key, _, value = chunk.strip().partition("=")
            if key:
                pairs[key.strip()] = value.strip()
        return pairs

    def save_cookies(self, path: str | None = None) -> str:
        target = path or self.cookie_file
        if not target:
            raise BiliError("未指定 cookie 保存路径")
        from pathlib import Path

        p = Path(target)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(self.export_cookies(), encoding="utf-8")
        try:
            p.chmod(0o600)
        except Exception:
            pass
        return str(p)

    def load_cookies(self, path: str | None = None) -> int:
        from pathlib import Path

        target = path or self.cookie_file
        if not target:
            return 0
        p = Path(target)
        if not p.exists():
            return 0
        return self.import_cookies(p.read_text(encoding="utf-8"))

    def _set_cookie(self, name: str, value: str) -> None:
        try:
            self.session.cookies.set(name, value, domain=".bilibili.com")
        except Exception:
            try:
                self.session.cookies.set(name, value)
            except Exception:
                pass

    # ------------------------------------------------------------ 限速

    def _throttle(self) -> None:
        with self._lock:
            gap = time.time() - self._last_call
            wait = self.min_delay - gap
            if wait > 0:
                time.sleep(wait)
            if self.jitter:
                time.sleep(random.uniform(0, self.jitter))
            self._last_call = time.time()

    # ------------------------------------------------------------ 底层请求

    def _raw(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        data: dict | None = None,
        headers: dict | None = None,
        binary: bool = False,
    ):
        kwargs: dict[str, Any] = {"timeout": self.timeout, "allow_redirects": True}
        if params:
            kwargs["params"] = params
        if data is not None:
            kwargs["data"] = data
        if headers:
            kwargs["headers"] = {**BASE_HEADERS, **headers}
        self._throttle()
        self.http_calls += 1
        return self.session.request(method, url, **kwargs)

    def request_json(
        self,
        url: str,
        params: dict | None = None,
        method: str = "GET",
        data: dict | None = None,
        headers: dict | None = None,
        wbi: bool = False,
        need_login: bool = False,
        retries: int | None = None,
        allow: tuple[int, ...] = (),
        soft: bool = False,
    ) -> dict:
        """发起请求并返回 `data`；业务 code 非 0 时抛对应异常。

        `allow` 列出**业务上可接受的非 0 code**：nav 在未登录时返回 -101，
        但响应体里仍然携带 wbi_img（签名必需），因此必须放行。

        `soft=True` 时完全不按业务 code 抛异常，直接把**完整响应体**
        （code/message/data）原样返回 —— 登录这类"失败也要看细节"的接口用。
        """
        payload = dict(params or {})
        if wbi:
            img_key, sub_key = self.wbi_keys()
            payload = wbi_mod.sign(payload, img_key, sub_key)

        attempts = self.retries if retries is None else retries
        # 软风控是**概率性**的（实测命中率约 60%，与 page 深浅/gaia 槽位/暖场都无关，
        # 见 tests/probe_search_paging_bound.py），因此不值得按普通错误计价：多试一次的
        # 边际收益很高（命中率 60% 时，8 次尝试的失败率 1.7%、11 次 0.36%、14 次 0.08%）。
        # 显式 `retries=0`（登录提交这类"明确不要重试"的调用）则完全尊重原意。
        soft_budget = attempts if attempts == 0 else max(attempts, self.soft_risk_retries)
        last: Exception | None = None
        attempt = 0
        soft_seen = 0
        while True:
            try:
                resp = self._raw(method, url, params=payload, data=data, headers=headers)
            except Exception as exc:  # 传输层
                last = TransportError(f"请求失败: {exc}", url=url)
                if attempt >= attempts:
                    break
                time.sleep(1.5 * (attempt + 1))
                attempt += 1
                continue

            status = resp.status_code
            if status == C.HTTP_RISK:
                self._log(f"RISK 412 {url}")
                last = RiskControl("触发风控（HTTP 412），建议降低频率或补充登录态", C.HTTP_RISK, url)
                if attempt >= attempts:
                    break
                time.sleep(3.0 * (attempt + 1))
                attempt += 1
                continue
            if status >= 500:
                last = TransportError(f"服务端 {status}", status, url)
                if attempt >= attempts:
                    break
                time.sleep(2.0 * (attempt + 1))
                attempt += 1
                continue
            if status != 200:
                last = TransportError(f"HTTP {status}", status, url)
                if attempt >= attempts:
                    break
                attempt += 1
                continue

            try:
                body = resp.json()
            except Exception:
                snippet = resp.text[:160].replace("\n", " ")
                if "风控" in resp.text or "security control" in resp.text:
                    last = RiskControl("触发风控（HTML 风控页）", C.HTTP_RISK, url)
                    if attempt >= attempts:
                        break
                    attempt += 1
                    continue
                last = BiliError(f"响应不是 JSON: {snippet}", url=url)
                if attempt >= attempts:
                    break
                attempt += 1
                continue

            code = int(body.get("code", 0))
            data = body.get("data")
            if soft:
                self._log(f"soft {url} code={code}")
                return body
            # 软风控：HTTP 200 + code 0，但业务载荷被 gaia 占位符 v_voucher 顶掉。
            # 成因是会话信誉的**概率性**抖动，不是频率也不是页数深浅。这里按独立预算
            # 多试几轮，并且每轮先**自愈**（重新暖场 + 续签 ticket + 刷新 wbi key）。
            if soft_risk_hit(body):
                soft_seen = attempt + 1
                self._log(f"SOFT-RISK v_voucher {url} -> 自愈+退避 (第 {soft_seen} 次)")
                last = SoftRisk(
                    "软风控：HTTP 200 + code 0，但响应被 gaia 占位符 v_voucher 顶掉"
                    "（没有业务数据）。这是会话信誉的概率性抖动，不是真的没有结果。",
                    url, attempts=soft_seen)
                if attempt < soft_budget:
                    self._recover_soft_risk(attempt)
                    attempt += 1
                    continue
                break
            if code == C.CODE_RISK and attempt < attempts:
                self._log(f"RISK -352 {url} -> backoff")
                last = RiskControl(body.get("message", ""), code, url)
                time.sleep(3.0 * (attempt + 1))
                attempt += 1
                continue
            if need_login and code == C.CODE_NOT_LOGIN:
                raise NotLoggedIn(body.get("message", ""), code, url)
            if code in allow:
                self._log(f"OK {url} code={code} (allowed)")
                return data
            if code == C.CODE_RISK and attempt >= attempts:
                raise RiskControl(body.get("message", ""), code, url)
            raise_for_code(code, body.get("message", ""), url)
            self._log(f"OK {url} code=0")
            return data

        raise last or BiliError("请求失败", url=url)

    def request_bytes(self, url: str, params: dict | None = None, wbi: bool = False,
                      retries: int = 2) -> bytes:
        """取二进制载荷（弹幕 protobuf 等）。

        304 视为"服务端让我复用缓存"，这里没有缓存层，直接重试一次拿完整体。
        """
        payload = dict(params or {})
        if wbi:
            img_key, sub_key = self.wbi_keys()
            payload = wbi_mod.sign(payload, img_key, sub_key)
        last: Exception | None = None
        for attempt in range(retries + 1):
            resp = self._raw("GET", url, params=payload)
            status = resp.status_code
            if status in (200, 206):
                return resp.content
            if status == 304:
                last = TransportError("HTTP 304（条件缓存命中）", status, url)
                time.sleep(0.6)
                continue
            if status == C.HTTP_RISK:
                last = RiskControl("触发风控（HTTP 412）", C.HTTP_RISK, url)
                time.sleep(2.5 * (attempt + 1))
                continue
            last = TransportError(f"HTTP {status}", status, url)
            time.sleep(1.2 * (attempt + 1))
        raise last or TransportError("二进制请求失败", url=url)

    def get_text(self, url: str, headers: dict | None = None) -> str:
        resp = self._raw("GET", url, headers=headers)
        return resp.text

    # ------------------------------------------------------------ 引导与会话

    def bootstrap(self) -> dict:
        """补齐无登录态风控 cookie：buvid3/buvid4/b_nut/b_lsid/_uuid。"""
        cookies = self.cookie_dict()
        if not cookies.get("buvid3") or not cookies.get("buvid4"):
            try:
                data = self.request_json(C.EP_SPI, headers={"Referer": C.WWW + "/"})
                if isinstance(data, dict) and data.get("b_3"):
                    self._set_cookie("buvid3", data["b_3"])
                    self._set_cookie("buvid4", data["b_4"])
                    self._log("bootstrap: buvid via spi")
            except Exception as exc:
                self._log(f"bootstrap spi failed: {exc}")
        if not self.cookie_dict().get("b_nut"):
            self._set_cookie("b_nut", str(int(time.time())))
        if not self.cookie_dict().get("_uuid"):
            self._set_cookie("_uuid", _rand_uuid())
        self._set_cookie("b_lsid", _rand_lsid())
        self.session.headers["Referer"] = C.WWW + "/"
        return self.cookie_dict()

    def warmup(self) -> None:
        """会话暖场：先落首页与搜索页 cookie，再打业务接口。

        实测价值：刚 bootstrap 出来的"全新 buvid 会话"直打搜索接口会返回
        v_voucher 软风控；暖场（并经一次退避重试）后同一请求返回完整 result。
        失败不致命（只记日志）。

        注意（实测量化，见 tests/probe_softrisk_fix.py / probe_search_gaia_ab.py）：
        对**已经有完整 cookie 的会话**，单次暖场并不能显著降低软风控命中率
        （60% -> 60%）；软风控是概率性的，请依靠 `request_json` 的多轮重试 +
        `_recover_soft_risk` 自愈，不要指望暖场单独救场。
        """
        for url, referer in (
            (C.WWW + "/", C.WWW + "/"),
            ("https://search.bilibili.com/all?keyword=%E5%8E%9F%E7%A5%9E", "https://search.bilibili.com/"),
        ):
            try:
                self.get_text(url, headers={"Referer": referer})
                self._log(f"warmup ok: {url[:48]}")
            except Exception as exc:
                self._log(f"warmup failed {url[:32]}: {exc}")

    def _recover_soft_risk(self, attempt: int = 0) -> None:
        """软风控自愈：退避 → （首次）完整会话刷新 → 续签 bili_ticket → 作废 wbi key。

        成本控制：暖场要拉首页 + 搜索页两个大页面，而它**已被实测否定了降低软风控
        命中率的作用**（60% -> 60%），所以只在**第一次**自愈时做完整刷新；之后每轮
        只做退避 + 续签 ticket（1 个轻请求）—— 省下来的请求直接换成更多重试轮次，
        对"软风控是概率性的"这件事更划算。

        `gen_ticket` 自己也会走 `request_json`，所以用 `_recovering` 防重入，
        避免软风控套娃。
        """
        if self._recovering:
            time.sleep(min(10.0, 2.0 * (attempt + 1)) + random.uniform(0, 1.0))
            return
        self._recovering = True
        try:
            time.sleep(min(8.0, 1.5 * (attempt + 1)) + random.uniform(0, 1.5))
            if attempt == 0:
                try:
                    self.warmup()
                except Exception as exc:  # noqa: BLE001
                    self._log(f"soft-risk warmup failed: {exc}")
            try:
                self.gen_ticket()
            except Exception as exc:  # noqa: BLE001
                self._log(f"soft-risk ticket failed: {exc}")
            self._wbi_keys = None
        finally:
            self._recovering = False

    def gen_ticket(self) -> str | None:
        """生成 bili_ticket（gaia 准入票据，24h 有效）。"""
        ts = int(time.time())
        hexsign = hmac.new(TICKET_HMAC_KEY, f"ts{ts}".encode(), hashlib.sha256).hexdigest()
        params = {"key_id": TICKET_KEY_ID, "hexsign": hexsign, "context[ts]": ts, "csrf": ""}
        try:
            data = self.request_json(
                C.EP_TICKET, params=params, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except Exception as exc:
            self._log(f"ticket failed: {exc}")
            return None
        ticket = (data or {}).get("ticket")
        if ticket:
            self._set_cookie("bili_ticket", ticket)
            self._set_cookie("bili_ticket_expires", str(ts + 3 * 24 * 3600))
            self._log("bootstrap: bili_ticket ok")
        return ticket

    def wbi_keys(self, refresh: bool = False) -> tuple[str, str]:
        """取当前会话的 (img_key, sub_key)。

        实测必须使用 /x/web-interface/nav 下发的 wbi_img；
        `__INITIAL_STATE__.defaultWbiKey` 是陈旧预置值，用它签名 0/6 匹配。
        """
        if self._wbi_keys and not refresh:
            return self._wbi_keys
        # 未登录时 nav 返回 -101，但 wbi_img 依然下发，因此放行该 code
        data = self.request_json(
            C.EP_NAV, headers={"Referer": C.WWW + "/"}, allow=(C.CODE_NOT_LOGIN,)
        )
        self._nav_cache = data if isinstance(data, dict) else {}
        self._wbi_keys = wbi_mod.keys_from_nav(self._nav_cache)
        return self._wbi_keys

    def nav(self, refresh: bool = False) -> dict:
        if self._nav_cache is None or refresh:
            self.wbi_keys(refresh=refresh)
        return self._nav_cache or {}

    def is_login(self) -> bool:
        return bool((self.nav() or {}).get("isLogin"))

    def self_mid(self) -> int:
        return int((self.nav() or {}).get("mid") or 0)

    def ensure_bootstrap(self) -> None:
        """补 cookie 后校验 nav 是否可用（未登录也应返回 wbi_img）。"""
        self.bootstrap()
        self.wbi_keys(refresh=True)

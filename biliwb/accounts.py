"""多账号池：每个账号一个独立 BiliClient（独立 cookie / 限速 / 身份）。

凭证安全
--------
* cookie 与密码**一律加密**后存库（`biliwb/secrets.py`：Windows DPAPI 优先，
  回退本机 Fernet 密钥）。库里没有明文。
* 对外接口（`list_public`）只返回脱敏信息与 `has_cookie` / `has_password` 布尔量，
  绝不回传凭证本体。

三种登录方式
------------
* `qr`       扫码（推荐）：不过验证码，cookie 直接落到该账号的 client
* `cookie`   粘贴导入（备用）
* `password` 账号密码自动登录：需先过极验 GT3（复用本工作区已验证的纯 Python 解算器）

密码登录的现实成本（实测）
--------------------------
* 验证码单轮约 13~17 秒（10~11 次请求），且 `gt/challenge/token` 约 **120 秒**就失效；
  登录端**先验验证码后验账号密码**，所以提交晚了必然返回 -105/-662。
  为此 `login_password` 用"会话内预取 + 硬预算 + 有界重试"把它变成确定性行为。
* 试错会累积**账号/IP 级**限流：-629（账号或密码错误次数过多）与验证码无关，
  冷却期内即使验证码通过也登不上。
因此**日常靠 cookie 复用**，只在 cookie 失效时才走密码登录。
"""

from __future__ import annotations

import base64
import threading
import time
from pathlib import Path
from typing import Any

from . import constants as C
from . import gt3
from . import riskverify
from .api import BiliAPI
from .client import BiliClient
from .errors import BiliError
from .login import LoginManager
from .secrets import SecretBox, mask
from .store import Store

# 密码登录业务码 -> 人话（实测/公开语义）
LOGIN_CODE_HINT = {
    0: "登录成功",
    -105: "验证码不被接受（token/challenge 已过期，或不是本次提交的会话预取的）",
    -400: "用户名或密码错误",
    -629: "账号或密码错误次数过多，请稍后再试",
    -662: "验证码已过期，请重试",
    1001: "账号格式错误",
    86038: "验证码已失效",
}

# 服务端"验证码这一关"的判决：与账号密码无关，重新预取重解即可。
CAPTCHA_REJECT_CODES = (-105, -662, 86038)

# 预取到提交之间允许消耗的秒数（含解算 + 加密 + 提交）。
# 实测边界：token 年龄 80s 仍通过，170s 返回 -105；这里取 75s 作为解算硬预算，
# 留出足够余量，宁可从零重来也不提交一个注定被拒的 validate。
SOLVE_BUDGET_S = 75.0


def rsa_encrypt(pubkey_pem: str, plain: str) -> str:
    """passport 的密码加密：RSA PKCS#1 v1.5 (hash + 明文密码) -> base64。"""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    pub = serialization.load_pem_public_key(pubkey_pem.encode("utf-8"))
    cipher = pub.encrypt(plain.encode("utf-8"), padding.PKCS1v15())
    return base64.b64encode(cipher).decode("ascii")


class AccountPool:
    """管理多个账号的客户端、凭证与登录。"""

    def __init__(
        self,
        store: Store,
        data_dir: str | Path = "data",
        min_delay: float = 1.1,
        impersonate: str = C.IMPERSONATE,
        midhash_index: Any = None,
    ) -> None:
        self.store = store
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.box = SecretBox(self.data_dir / ".secret.key")
        self.min_delay = float(min_delay)
        self.impersonate = impersonate
        self.midhash_index = midhash_index

        self._clients: dict[int, BiliClient] = {}
        self._apis: dict[int, BiliAPI] = {}
        self._locks: dict[int, threading.Lock] = {}
        # status=2（服务端要求短信二次验证）之后待处理的上下文：账号 -> challenge 参数
        self._risk_ctx: dict[int, dict] = {}
        # 必须是**可重入**锁：api() 会在持有它时调用 client()（后者也要用它）。
        # 用普通 Lock 会在同一线程内自死锁 —— 曾导致所有账号校验请求永久挂死。
        self._guard = threading.RLock()

    # ------------------------------------------------------------ 账号 CRUD

    def create(self, alias: str, login_method: str = "qr",
               username: str | None = None, password: str | None = None,
               cookie: str | None = None) -> dict:
        alias = (alias or "").strip()
        if not alias:
            raise ValueError("alias 不能为空")
        if login_method not in ("qr", "password", "cookie"):
            raise ValueError(f"login_method 非法: {login_method}")
        if self.store.get_account_by_alias(alias):
            raise ValueError(f"账号别名已存在: {alias}")
        if login_method == "password" and not (username and password):
            raise ValueError("密码登录需要同时提供 username 与 password")

        account_id = self.store.create_account(
            alias, login_method=login_method, username=username,
            password_enc=self.box.protect(password),
            cookie_enc=self.box.protect(cookie),
        )
        return self.get_public(account_id)

    def delete(self, account_id: int) -> bool:
        with self._guard:
            self._clients.pop(account_id, None)
            self._apis.pop(account_id, None)
            self._locks.pop(account_id, None)
        return self.store.delete_account(account_id)

    def set_credentials(self, account_id: int, username: str | None = None,
                        password: str | None = None, cookie: str | None = None) -> dict:
        acc = self.store.get_account(account_id)
        if not acc:
            raise BiliError(f"账号不存在: {account_id}")
        fields: dict[str, Any] = {}
        if username is not None:
            fields["username"] = username
        if password is not None:
            fields["password_enc"] = self.box.protect(password)
        if cookie is not None:
            fields["cookie_enc"] = self.box.protect(cookie)
        if fields:
            self.store.update_account(account_id, **fields)
        return self.get_public(account_id)

    def get_public(self, account_id: int) -> dict:
        acc = self.store.get_account(account_id)
        if not acc:
            raise BiliError(f"账号不存在: {account_id}")
        return self._to_public(acc)

    def list_public(self) -> list[dict]:
        return [self._to_public(a) for a in self.store.list_accounts()]

    def _to_public(self, acc: dict) -> dict:
        """脱敏：绝不回传 cookie / 密码本体。"""
        return {
            "id": acc["id"],
            "alias": acc["alias"],
            "mid": acc.get("mid"),
            "uname": acc.get("uname"),
            "face": acc.get("face"),
            "login_method": acc.get("login_method"),
            "username": acc.get("username"),
            "has_password": bool(acc.get("password_enc")),
            "has_cookie": bool(acc.get("cookie_enc")),
            "enabled": bool(acc.get("enabled", 1)),
            "last_status": acc.get("last_status"),
            "last_error": acc.get("last_error"),
            "last_verified_at": acc.get("last_verified_at"),
            "cookie_hint": mask(self._peek_cookie(acc), 6),
        }

    def _peek_cookie(self, acc: dict) -> str | None:
        blob = acc.get("cookie_enc")
        if not blob:
            return None
        try:
            return self.box.unprotect(blob)
        except Exception:
            return None

    # ------------------------------------------------------------ 客户端

    def lock(self, account_id: int) -> threading.Lock:
        """账号级串行锁：同一账号同时只允许一个请求在跑（避免风控）。"""
        with self._guard:
            if account_id not in self._locks:
                self._locks[account_id] = threading.Lock()
            return self._locks[account_id]

    def client(self, account_id: int) -> BiliClient:
        with self._guard:
            cached = self._clients.get(account_id)
            if cached is not None:
                return cached
        acc = self.store.get_account(account_id)
        if not acc:
            raise BiliError(f"账号不存在: {account_id}")
        cli = BiliClient(cookie_file=None, min_delay=self.min_delay,
                         impersonate=self.impersonate)
        cli.midhash_index = self.midhash_index
        raw = self._peek_cookie(acc)
        if raw:
            cli.import_cookies(raw)
        # 会话身份必须在**任务发出第一个业务请求之前**补齐：缺少 buvid3/buvid4/
        # b_nut/_uuid 的裸会话打搜索这类接口会高概率吃 v_voucher 软风控
        # （实测命中率 ~45%，且与 page 深浅无关）。bootstrap 自身幂等，失败不致命。
        try:
            cli.bootstrap()
        except Exception as exc:  # noqa: BLE001
            print(f"[accounts] bootstrap({account_id}) 失败: {type(exc).__name__}: {exc}",
                  file=__import__("sys").stderr)
        with self._guard:
            self._clients[account_id] = cli
            return cli

    def api(self, account_id: int) -> BiliAPI:
        with self._guard:
            cached = self._apis.get(account_id)
            if cached is not None:
                return cached
        # 构造放在锁外：client() 自己会取锁，且 BiliClient 构造可能读凭证
        client = self.client(account_id)
        # 多账号模式下 cookie 只存加密账号库；下面的路径仅作占位，
        # 因为 LoginManager 的 save() 在全流程里都以 autosave=False 调用。
        placeholder = self.data_dir / ".accounts-session-placeholder"
        api = BiliAPI(client, session_path=placeholder)
        with self._guard:
            existing = self._apis.get(account_id)
            if existing is not None:
                return existing
            self._apis[account_id] = api
            return api

    def persist_cookie(self, account_id: int) -> bool:
        """把 client 当前的 cookie 加密写回库（会话续期后调用）。"""
        cli = self._clients.get(account_id)
        if not cli:
            return False
        self.store.update_account(
            account_id, cookie_enc=self.box.protect(cli.export_cookies()))
        return True

    def clear_cache(self, account_id: int | None = None) -> None:
        with self._guard:
            if account_id is None:
                self._clients.clear()
                self._apis.clear()
            else:
                self._clients.pop(account_id, None)
                self._apis.pop(account_id, None)

    # ------------------------------------------------------------ 登录

    def qr_start(self, account_id: int) -> dict:
        api = self.api(account_id)
        cli = self.client(account_id)
        cli.bootstrap()
        cli.warmup()
        return api.login.qr_start()

    def qr_poll(self, account_id: int, qrcode_key: str) -> dict:
        api = self.api(account_id)
        result = api.login.qr_poll(qrcode_key, autosave=False)
        if result.get("logged_in"):
            self._after_login(account_id, method="qr")
            result["account"] = self.get_public(account_id)
        return result

    def import_cookie(self, account_id: int, cookie: str) -> dict:
        cli = self.client(account_id)
        count = cli.import_cookies(cookie)
        # 重建 client 缓存，避免旧 cookie 残留
        cli._wbi_keys = None
        cli._nav_cache = None
        self.persist_cookie(account_id)
        self.store.update_account(account_id, login_method="cookie")
        info = self.verify(account_id)
        info["imported"] = count
        return info

    def login_password(self, account_id: int, source: str = "main-fe",
                       gt3_timeout: int | None = None,
                       attempts: int = 2) -> dict:
        """账号密码自动登录（过极验 GT3）。

        验证码的现实约束（本机实测，见 tests/captcha_ttl.py）
        ----------------------------------------------------
        passport 下发的 `gt/challenge/token` 是**会过期**的：预取到提交 116s 时登录端
        仍接受，160s 时返回 -105「验证码错误」（即寿命约 120s）。而登录端**先验验证码、
        后验账号密码**（不带验证码字段时直接 -105），所以提交晚了的话，即使极验自己
        回了 validate，也 100% 被拒 —— 这正是"经常提示验证码已过期 / 登录失败"的根因。

        因此这里：
        1. 验证码由**即将提交登录的同一个 client 会话**预取（与浏览器一致），
           这样 token 的签发时刻是我们自己掌握的；
        2. 解算带**硬时间预算**，超预算就整轮丢弃，绝不提交注定过期的 validate；
        3. 被 -105/-662 拒绝时**重新预取 + 重解 + 重提**（有界重试）。
        """
        acc = self.store.get_account(account_id)
        if not acc:
            raise BiliError(f"账号不存在: {account_id}")
        username = acc.get("username")
        password = self.box.unprotect(acc.get("password_enc"))
        if not username or not password:
            raise BiliError("该账号没有保存账号名/密码，无法自动登录")

        budget = float(gt3_timeout or SOLVE_BUDGET_S)
        total = max(1, int(attempts))

        result: dict[str, Any] = {"account_id": account_id, "stage": "start"}
        cli = self.client(account_id)
        cli.bootstrap()
        cli.warmup()
        cli.gen_ticket()

        history: list[dict] = []
        result["attempts_allowed"] = total

        for attempt in range(1, total + 1):
            attempt_rec: dict[str, Any] = {"attempt": attempt}
            history.append(attempt_rec)

            # 1) 用**本会话**预取验证码（gt / challenge / token 三者同轮）
            result["stage"] = "captcha_prefetch"
            try:
                cap_pre = self._captcha_prefetch(cli, source)
            except Exception as exc:  # noqa: BLE001
                attempt_rec["error"] = f"预取失败: {type(exc).__name__}: {exc}"
                result.update({"ok": False, "stage": "captcha_prefetch",
                               "error": attempt_rec["error"]})
                break
            attempt_rec["captcha_type"] = cap_pre.get("type")
            if not (cap_pre.get("gt") and cap_pre.get("challenge")):
                # 服务端此刻没派 geetest（例如派了图形验证码通道）——无法自动过
                result.update({
                    "ok": False, "stage": "captcha_prefetch",
                    "error": f"服务端未派发 geetest 通道（type={cap_pre.get('type')}）",
                    "captcha_init": {k: cap_pre.get(k) for k in ("type", "token")},
                })
                break

            # 2) 过极验 GT3（带硬时间预算）
            result["stage"] = "captcha"
            try:
                cap = gt3.solve_once(
                    source=source, timeout=int(max(20, budget)),
                    gt=cap_pre["gt"], challenge=cap_pre["challenge"],
                    token=cap_pre["token"])
            except gt3.Gt3Unavailable as exc:
                result.update({"ok": False, "stage": "captcha",
                               "error": f"GT3 解算器不可用: {exc}"})
                break

            age = round(cap.get("seconds") or 0.0, 1)
            attempt_rec["solve"] = {
                "ok": cap.get("ok"), "seconds": age, "score": cap.get("score"),
                "verdict": cap.get("verdict"), "http_used": cap.get("http_used"),
                "error": cap.get("error"),
            }
            result["captcha"] = {"score": cap.get("score"), "seconds": age}
            if not cap.get("ok"):
                attempt_rec["error"] = cap.get("error") or "验证码求解失败"
                result.update({"ok": False, "stage": "captcha",
                               "error": attempt_rec["error"],
                               "verdict": cap.get("verdict"),
                               "log_tail": cap.get("log_tail")})
                continue  # 换一轮新 challenge 重来
            if age > budget:
                # 已经在预算外拿到 validate，直接作废：提交必被 -105/-662 拒绝
                attempt_rec["error"] = f"解算耗时 {age}s 超出 {budget:.0f}s 预算，validate 已作废"
                result.update({"ok": False, "stage": "captcha", "error": attempt_rec["error"]})
                continue

            # 3) RSA 加密（每次尝试都重新取 key：hash 会随会话轮换）
            result["stage"] = "rsa"
            try:
                key_data = cli.request_json(
                    C.EP_LOGIN_KEY, params={"_": int(time.time() * 1000)},
                    soft=True, retries=1)
            except Exception as exc:  # noqa: BLE001
                attempt_rec["error"] = f"{type(exc).__name__}: {exc}"
                result.update({"ok": False, "stage": "key", "error": attempt_rec["error"]})
                break
            keyinfo = (key_data if isinstance(key_data, dict) else {}).get("data") or {}
            pubkey, salt = keyinfo.get("key"), keyinfo.get("hash")
            if not pubkey or not salt:
                result.update({"ok": False, "stage": "key",
                               "error": f"未取得 RSA 公钥: {key_data}"})
                break
            try:
                encrypted = rsa_encrypt(pubkey, f"{salt}{password}")
            except Exception as exc:  # noqa: BLE001
                result.update({"ok": False, "stage": "rsa",
                               "error": f"{type(exc).__name__}: {exc}"})
                break

            # 4) 提交
            result["stage"] = "submit"
            try:
                resp = cli.request_json(C.EP_LOGIN, method="POST", data={
                    "source": source,
                    "username": username,
                    "password": encrypted,
                    "validate": cap["validate"],
                    "seccode": cap["seccode"],
                    "challenge": cap["challenge"],
                    "token": cap["token"],
                    "sns_platform": "",
                    "sns_openid": "",
                    "csrf": cli.cookie_dict().get("bili_jct", ""),
                    "go_url": "https://www.bilibili.com/",
                }, soft=True, retries=0, headers={"Referer": C.WWW + "/"})
            except Exception as exc:  # noqa: BLE001
                result.update({"ok": False, "stage": "submit",
                               "error": f"{type(exc).__name__}: {exc}"})
                break

            rbody = resp if isinstance(resp, dict) and "code" in resp else {"code": 0, "data": resp}
            code = int(rbody.get("code", -1))
            rdata = rbody.get("data") or {}
            token_age = round(time.time() - cap_pre["issued_at"], 1)
            attempt_rec["submit"] = {
                "code": code, "message": rbody.get("message"), "token_age": token_age,
            }
            result.update({
                "code": code, "message": rbody.get("message"),
                "hint": LOGIN_CODE_HINT.get(code, ""),
                "token_age": token_age,
                "attempts_used": attempt,
                "data": {k: v for k, v in rdata.items()
                         if k in ("status", "url", "refresh_token", "timestamp")},
                "_echo": {k: mask(cap.get(k), 6)
                          for k in ("validate", "seccode", "challenge", "token")},
            })

            if code == 0 and int(rdata.get("status", 0)) == 0:
                self._after_login(account_id, method="password")
                result.update({"ok": True, "stage": "done",
                               "account": self.get_public(account_id)})
                result["attempt_history"] = history
                return result

            if code == 0:
                # code=0 但 status!=0：服务端要求**额外的安全验证**。
                # 浏览器端此时执行 location.replace(data.url)，即跳到 B 站的验证页
                # （短信/安全问题/人机校验等）。纯协议无法代替用户完成这一步，
                # 所以这里必须把 status 与 url **如实交出去**，而不是只报一句
                # "需要额外验证"。旧实现把 url 截断进 last_error，前端根本看不到。
                status = int(rdata.get("status") or 0)
                challenge_url = rdata.get("url")
                # 记下 tmp_token/request_id/source，供后续"半自动短信验证"接续
                ctx = riskverify.parse_challenge_url(challenge_url or "")
                if ctx.get("tmp_token"):
                    ctx["issued_at"] = time.time()
                    with self._guard:
                        self._risk_ctx[account_id] = ctx
                result.update({
                    "ok": False,
                    "stage": "challenge",
                    "status": status,
                    "challenge_url": challenge_url,
                    "risk_pending": bool(ctx.get("tmp_token")),
                    "error": f"服务端要求额外安全验证（status={status}）",
                    "hint": ("这是 B 站的风控二次验证：实测 status=2 要求短信校验你的绑定手机号。"
                             "工作台会直接在弹窗里走完：协议负责过人机验证码 + 发短信 + 换 cookie，"
                             "你只需把手机收到的验证码填进弹窗即可。"),
                    "data": {k: v for k, v in rdata.items()
                             if k in ("status", "url", "mid", "timestamp")},
                })
                self.store.update_account(
                    account_id, last_status="challenge",
                    last_error=f"status={status} {str(challenge_url)[:200]}")
                result["attempt_history"] = history
                return result

            if code in CAPTCHA_REJECT_CODES:
                # 验证码这一关的判决：与账号密码无关，重来一轮才有意义
                attempt_rec["error"] = f"{code}: {rbody.get('message')}"
                if attempt < total:
                    result["stage"] = "captcha_retry"
                    continue
                result.update({"ok": False, "stage": "rejected",
                               "error": (f"验证码连续 {total} 次被服务端拒绝"
                                         f"（{code}: {rbody.get('message')}）。"
                                         "若反复出现，请稍后再试或改用扫码登录。")})
            else:
                result.update({"ok": False, "stage": "rejected"})

            self.store.update_account(account_id, last_status="failed",
                                      last_error=f"{code}: {rbody.get('message')}")
            result["attempt_history"] = history
            return result

        # 循环走完仍未成功（解算连续失败 / 超预算 / 预取异常）
        result.setdefault("ok", False)
        result["attempt_history"] = history
        if result.get("stage") in ("captcha", "captcha_retry"):
            result["stage"] = "captcha"
            result["error"] = (f"极验 GT3 连续 {total} 次未通过或在预算内未完成："
                               f"{result.get('error') or '未取得 validate'}")
            result["captcha_help"] = (
                f"已限制单轮解算 {budget:.0f}s：超过它拿到的 validate 提交必被 -105 拒绝")
        self.store.update_account(account_id, last_status="failed",
                                  last_error=str(result.get("error"))[:300])
        return result

    def _captcha_prefetch(self, cli: "BiliClient", source: str) -> dict:
        """在即将提交登录的那个会话里预取验证码，返回 gt/challenge/token 与签发时刻。"""
        body = cli.request_json(
            C.EP_CAPTCHA,
            params={"source": source, "_": int(time.time() * 1000)},
            soft=True, retries=1,
            headers={"Referer": C.PASSPORT + "/login"},
        )
        data = (body if isinstance(body, dict) else {}).get("data") or {}
        gee = data.get("geetest") or {}
        if data.get("recaptcha_type"):
            # 兼容 recaptcha_* 这套旧 schema（字段名不同、语义相同）
            gee = {"gt": data.get("gee_gt"), "challenge": data.get("gee_challenge")}
            data = {"type": data.get("recaptcha_type"), "token": data.get("recaptcha_token")}
        return {
            "type": data.get("type"),
            "token": data.get("token"),
            "gt": gee.get("gt"),
            "challenge": gee.get("challenge"),
            "issued_at": time.time(),
        }

    def _risk_context(self, account_id: int) -> dict:
        with self._guard:
            ctx = self._risk_ctx.get(account_id)
        if not ctx:
            # 进程重启会丢掉内存态：从库里存的 last_error（形如 "status=2 <url>"）恢复，
            # 否则用户重启一次工作台就得重新撞一遍密码登录。
            acc = self.store.get_account(account_id) or {}
            err = acc.get("last_error") or ""
            if acc.get("last_status") == "challenge" and "tmp_token=" in err:
                url = err.split(" ", 1)[1].strip() if " " in err else ""
                recovered = riskverify.parse_challenge_url(url)
                if recovered.get("tmp_token"):
                    recovered["issued_at"] = float(acc.get("updated_at") or 0)
                    with self._guard:
                        self._risk_ctx[account_id] = recovered
                    ctx = recovered
        if not ctx:
            raise BiliError(
                "没有待处理的二次验证：请先点一次「密码」登录，"
                "等它返回 status=2（需要短信验证）后再走这一步")
        age = time.time() - float(ctx.get("issued_at") or 0)
        if age > 900:
            with self._guard:
                self._risk_ctx.pop(account_id, None)
            raise BiliError(f"二次验证上下文已过期（{age:.0f}s 前签发），请重新执行一次密码登录")
        ctx["age"] = round(age, 1)
        return ctx

    def risk_status(self, account_id: int) -> dict:
        """二次验证的当前进度：有没有待处理上下文、短信是否已经发出去了。"""
        try:
            ctx = self._risk_context(account_id)
        except BiliError as exc:
            return {"pending": False, "hint": str(exc)}
        return {
            "pending": True,
            "captcha_sent": bool(ctx.get("captcha_key")),
            "sms_type": riskverify.sms_type_of(ctx),
            "age": ctx.get("age"),
        }

    def risk_send_sms(self, account_id: int, captcha_timeout: int = 75) -> dict:
        """status=2 的第二步：过掉人机验证码 → 给绑定手机发短信。

        自动化的是"过人机验证码 + 发短信"；短信内容只有用户本人能看到，
        所以下一步 `risk_verify_sms` 必须由用户把验证码交回来。
        """
        ctx = self._risk_context(account_id)
        cli = self.client(account_id)
        pre = riskverify.captcha_pre(cli, ctx)
        fields = riskverify.solve_captcha(cli, pre, timeout=captcha_timeout)
        sent = riskverify.send_sms(cli, ctx, fields)
        with self._guard:
            ctx["captcha_key"] = sent["captcha_key"]
        return {
            "ok": True,
            "account_id": account_id,
            "captcha_type": pre.get("type"),
            "solve": fields.get("_solve"),
            "sms_type": riskverify.sms_type_of(ctx),
            "tmp_token_age": ctx["age"],
            "hint": "短信已发往该账号绑定的手机，请把收到的验证码填进来完成验证",
        }

    def risk_verify_sms(self, account_id: int, code: str) -> dict:
        """status=2 的第三步：提交短信验证码 → exchange_cookie → 落库。"""
        code = (code or "").strip()
        if not code:
            raise BiliError("请填写手机收到的短信验证码")
        ctx = self._risk_context(account_id)
        captcha_key = ctx.get("captcha_key")
        if not captcha_key:
            raise BiliError("请先点「发短信验证」获取验证码，再填短信码")
        cli = self.client(account_id)
        ticket = riskverify.verify_sms(cli, ctx, captcha_key, code)
        ex = riskverify.exchange_cookie(cli, ctx, ticket)
        result = {"ok": bool(ex.get("ok")), "account_id": account_id,
                  "stage": "risk_done" if ex.get("ok") else "risk_exchange_failed",
                  "exchange": {k: ex.get(k) for k in ("code", "message", "has_sessdata", "http")}}
        if ex.get("ok"):
            with self._guard:
                self._risk_ctx.pop(account_id, None)
            self._after_login(account_id, method="password")
            result["account"] = self.get_public(account_id)
            result["hint"] = "短信验证通过，登录态已落到该账号"
        else:
            result["error"] = f"换 cookie 失败: {ex.get('message') or ex.get('http')}"
        return result

    def _after_login(self, account_id: int, method: str) -> None:
        cli = self.client(account_id)
        cli._wbi_keys = None
        cli._nav_cache = None
        self.persist_cookie(account_id)
        nav = cli.nav(refresh=True)
        self.store.update_account(
            account_id,
            mid=nav.get("mid"), uname=nav.get("uname"), face=nav.get("face"),
            login_method=method, last_status="ok", last_error=None,
            last_verified_at=int(time.time()),
        )

    # ------------------------------------------------------------ 校验

    def verify(self, account_id: int) -> dict:
        """校验单个账号的会话有效性，并把最新 cookie 加密写回。"""
        cli = self.client(account_id)
        out: dict[str, Any] = {"account_id": account_id}
        try:
            cli.bootstrap()
        except Exception as exc:
            print(f"[accounts] bootstrap({account_id}) 失败: {type(exc).__name__}: {exc}",
                  file=__import__("sys").stderr)
        try:
            api = self.api(account_id)
            info = api.login.verify()
            if not info.get("logged_in") and not info.get("error"):
                # 冷启动偶发：暖场 + 续签 bili_ticket 后再判一次
                cli.warmup()
                cli.gen_ticket()
                info = api.login.verify()
        except Exception as exc:
            out.update({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            self.store.update_account(account_id, last_status="error",
                                      last_error=str(exc)[:300],
                                      last_verified_at=int(time.time()))
            return out

        out["ok"] = bool(info.get("logged_in"))
        out["mid"] = info.get("mid")
        out["uname"] = info.get("uname")
        out["level"] = info.get("level")
        out["has_sessdata"] = info.get("has_sessdata")
        out["cookie_refresh_recommended"] = info.get("cookie_refresh_recommended")
        if info.get("error"):
            out["error"] = info["error"]

        if out["ok"]:
            cli = self.client(account_id)
            self.store.update_account(
                account_id, mid=info.get("mid"), uname=info.get("uname"),
                face=info.get("face"), last_status="ok", last_error=None,
                last_verified_at=int(time.time()))
            self.persist_cookie(account_id)
        else:
            self.store.update_account(account_id, last_status="expired",
                                      last_error=out.get("error") or "会话无效",
                                      last_verified_at=int(time.time()))
        return out

    def verify_all(self, workers: int = 4) -> list[dict]:
        """并发校验所有账号。"""
        accounts = [a for a in self.store.list_accounts()]
        if not accounts:
            return []
        results: dict[int, dict] = {}
        errors: list[dict] = []
        lock = threading.Lock()
        queue = [a["id"] for a in accounts]

        def worker() -> None:
            while True:
                with lock:
                    if not queue:
                        return
                    account_id = queue.pop(0)
                try:
                    res = self.verify(account_id)
                except Exception as exc:  # noqa: BLE001
                    res = {"account_id": account_id, "ok": False,
                           "error": f"{type(exc).__name__}: {exc}"}
                with lock:
                    results[account_id] = res

        threads = [threading.Thread(target=worker, daemon=True)
                   for _ in range(max(1, min(workers, len(accounts))))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        out = []
        for acc in accounts:
            res = results.get(acc["id"], {"account_id": acc["id"], "ok": False,
                                          "error": "未执行"})
            res["alias"] = acc["alias"]
            out.append(res)
        return out

    # ------------------------------------------------------------ 任务分配

    def healthy_ids(self) -> list[int]:
        return [a["id"] for a in self.store.list_accounts()
                if a.get("enabled", 1) and a.get("last_status") == "ok"]

    def pick(self, exclude: set[int] | None = None) -> int | None:
        """挑一个可用账号（优先最近校验成功的）。"""
        exclude = exclude or set()
        usable = [a for a in self.store.list_accounts()
                  if a.get("enabled", 1) and a["id"] not in exclude]
        if not usable:
            return None
        ok = [a for a in usable if a.get("last_status") == "ok"]
        pool = ok or usable
        pool.sort(key=lambda a: (a.get("last_verified_at") or 0), reverse=True)
        return pool[0]["id"]

    def describe_security(self) -> dict:
        return self.box.describe()

"""登录与会话：扫码登录、cookie 持久化、会话有效性校验。

为什么用扫码而不是密码登录
--------------------------
密码通道必须先过极验 GT3 验证码（本工作区 `js_reverse_cache/tasks/bili-gt3-solver`
有可用的免浏览器求解器，但成本高、失败有账号风险）。扫码通道**不经过验证码**，
且 cookie 由 passport 直接下发到本地会话，是最稳的本地登录路径。
密码/短信通道保留为后续可插拔选项。

会话有效性
----------
* `bili_ticket` 24h 过期 -> 用已知 HMAC 算法本地自动续期（client.gen_ticket）。
* `SESSDATA` 由服务端决定有效期 -> 本地持久化复用，并提供手动校验。
* `x/passport-login/web/cookie/info` 的 `refresh` 字段用于提示是否需要重新登录。
"""

from __future__ import annotations

import time
from pathlib import Path

from . import constants as C
from .client import BiliClient
from .errors import BiliError

POLL_STATE = {
    0: "登录成功",
    86038: "二维码已失效，请重新生成",
    86090: "已扫码，请在手机上确认",
    86101: "等待扫码",
}


class LoginManager:
    def __init__(self, client: BiliClient, session_path: str | Path = "session.txt") -> None:
        self.client = client
        self.session_path = Path(session_path)
        self._qr: dict | None = None

    # ------------------------------------------------------------ 扫码登录

    def qr_start(self) -> dict:
        """申请二维码。返回 {qrcode_key, url, svg}，svg 为 data URI 可直接 <img src>。"""
        data = self.client.request_json(
            C.EP_QR_GENERATE, headers={"Referer": C.WWW + "/"}
        )
        key = (data or {}).get("qrcode_key")
        url = (data or {}).get("url")
        if not key or not url:
            raise BiliError(f"二维码申请失败: {data}")
        self._qr = {"qrcode_key": key, "url": url, "ts": time.time()}
        return {"qrcode_key": key, "url": url, "svg": _qr_svg(url)}

    def qr_poll(self, qrcode_key: str, autosave: bool = True) -> dict:
        """轮询扫码状态；成功时 cookie 已落在 client.session 上。

        `autosave=False` 时不写明文 session.txt —— 多账号模式由账号库
        加密保存 cookie（见 accounts.AccountPool）。
        """
        data = self.client.request_json(
            C.EP_QR_POLL,
            params={"qrcode_key": qrcode_key, "source": "main-fe-header"},
            headers={"Referer": C.WWW + "/"},
            allow=(0,),
        )
        inner_code = int((data or {}).get("code", -1))
        result = {
            "state_code": inner_code,
            "state": POLL_STATE.get(inner_code, f"未知状态 {inner_code}"),
            "logged_in": inner_code == 0,
        }
        if inner_code == 0:
            self.client._wbi_keys = None
            self.client._nav_cache = None
            if autosave:
                result["saved_to"] = self.save()
            result["session"] = self.verify()
        return result

    # ------------------------------------------------------------ 持久化

    def save(self) -> str:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_path.write_text(self.client.export_cookies(), encoding="utf-8")
        try:
            self.session_path.chmod(0o600)
        except Exception:
            pass
        return str(self.session_path)

    def load(self) -> int:
        return self.client.load_cookies(str(self.session_path))

    def clear(self) -> None:
        if self.session_path.exists():
            self.session_path.unlink()

    # ------------------------------------------------------------ 校验

    def verify(self) -> dict:
        """手动会话校验：返回登录态、uid、昵称、等级、cookie 健康度。"""
        out: dict = {"logged_in": False}
        try:
            nav = self.client.nav(refresh=True)
        except Exception as exc:
            out["error"] = f"{type(exc).__name__}: {exc}"
            return out
        out["logged_in"] = bool(nav.get("isLogin"))
        out["mid"] = nav.get("mid")
        out["uname"] = nav.get("uname")
        out["face"] = nav.get("face")
        out["level"] = (nav.get("level_info") or {}).get("current_level")
        out["coins"] = nav.get("money")
        out["vip"] = (nav.get("vipStatus") or 0) == 1

        cookies = self.client.cookie_dict()
        out["has_sessdata"] = bool(cookies.get("SESSDATA"))
        out["has_bili_jct"] = bool(cookies.get("bili_jct"))
        out["has_buvid3"] = bool(cookies.get("buvid3"))
        out["session_file"] = str(self.session_path)
        out["session_file_exists"] = self.session_path.exists()

        if out["logged_in"]:
            try:
                info = self.client.request_json(
                    C.EP_COOKIE_INFO, wbi=True, retries=0,
                    headers={"Referer": C.WWW + "/"},
                )
                out["cookie_refresh_recommended"] = bool((info or {}).get("refresh"))
            except Exception as exc:
                out["cookie_info_error"] = f"{type(exc).__name__}: {exc}"
        return out


def _qr_svg(url: str) -> str:
    """把登录 URL 渲染成 SVG data URI（纯 Python，无 JS/无外部请求）。"""
    try:
        import segno
    except ImportError as exc:  # 我们自己的依赖缺失，必须响亮
        raise BiliError(f"缺少二维码依赖 segno: {exc}") from exc
    return segno.make(url, error="m").svg_data_uri(scale=4, border=2)

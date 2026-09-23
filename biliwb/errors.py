"""异常与错误码语义。"""

from __future__ import annotations

from .constants import ERROR_SEMANTICS


class BiliError(Exception):
    """所有 bilibili 采集错误的基类。"""

    def __init__(self, message: str, code: int | None = None, url: str = ""):
        super().__init__(message)
        self.code = code
        self.url = url

    def __str__(self) -> str:
        base = super().__str__()
        if self.code is None:
            return base
        return f"[{self.code}] {base}"


class NotLoggedIn(BiliError):
    """需要登录态（code -101）。"""


class RiskControl(BiliError):
    """风控拦截：HTTP 412 风控页，或 code -352。"""


class SoftRisk(RiskControl):
    """**软风控**：HTTP 200 + code 0，但业务载荷被 gaia 占位符 `v_voucher` 顶掉。

    它与"真的没有数据"必须分开：搜索/评论的深分页里，把它当成空结果会**静默丢数据**。
    实测它的成因是**会话信誉的概率性抖动**（不是频率，也不是页数深浅）：同一会话、
    同一 page 反复请求，命中率约 60%，且与 page 深浅、gaia 指纹槽位、暖场都
    **没有**显著关系（交替 A/B 已证，见 tests/probe_search_paging_bound.py 与
    tests/probe_search_gaia_ab.py）。因此唯一的确定性解法是"多试几轮 + 每轮自愈"。

    它是 `RiskControl` 的子类，因此既有的 `except RiskControl` 仍然生效。
    """

    def __init__(self, message: str, url: str = "", attempts: int = 0):
        super().__init__(message, None, url)
        self.attempts = attempts


class PrivacyLimited(BiliError):
    """对方隐私设置导致不可见（关注/粉丝列表等）。"""


class NotFound(BiliError):
    """目标不存在或不可见。"""


class TransportError(BiliError):
    """网络/传输层失败。"""


def semantic(code: int | None) -> str:
    if code is None:
        return "未知错误"
    return ERROR_SEMANTICS.get(code, f"未收录错误码 {code}")


def raise_for_code(code: int, message: str = "", url: str = "") -> None:
    """把 bilibili 业务 code 映射为异常；code==0 直接返回。"""
    if code == 0:
        return
    text = message or semantic(code)
    if code == -101:
        raise NotLoggedIn(text, code, url)
    if code in (-352, -412):
        raise RiskControl(text, code, url)
    if code == -400:
        raise PrivacyLimited(text, code, url)
    if code == -404:
        raise NotFound(text, code, url)
    raise BiliError(text, code, url)

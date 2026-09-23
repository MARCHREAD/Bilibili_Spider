"""本地凭证加密（cookie / 密码绝不落明文）。

策略
----
1. **Windows DPAPI**（首选）：`CryptProtectData`，密钥由当前 Windows 用户凭据派生。
   密文只有**同一台机器的同一用户**能解；换机器或换用户即失效。
2. **Fernet 回退**（非 Windows 或缺少 pywin32）：本机随机密钥文件（0600）+ AES。

密文自带后端前缀，解密时自动识别，因此以后换后端也能读旧数据。
"""

from __future__ import annotations

import os
import pathlib

DPAPI_PREFIX = b"DPAPI1:"
FERNET_PREFIX = b"FERNET1:"

try:  # pragma: no cover - 取决于运行平台
    import win32crypt  # type: ignore

    _HAS_DPAPI = True
except Exception:  # noqa: BLE001
    win32crypt = None  # type: ignore
    _HAS_DPAPI = False


class SecretBox:
    """把字符串加密为字节、再解回字符串。"""

    def __init__(self, key_path: str | pathlib.Path = "data/.secret.key") -> None:
        self.key_path = pathlib.Path(key_path)
        self.backend = "dpapi" if _HAS_DPAPI else "fernet"

    # ------------------------------------------------------------ 内部

    def _fernet(self):
        from cryptography.fernet import Fernet

        if not self.key_path.exists():
            self.key_path.parent.mkdir(parents=True, exist_ok=True)
            self.key_path.write_bytes(Fernet.generate_key())
            try:
                self.key_path.chmod(0o600)
            except Exception:
                pass
        return Fernet(self.key_path.read_bytes())

    # ------------------------------------------------------------ 公开

    def protect(self, text: str | None) -> bytes | None:
        if text is None or text == "":
            return None
        raw = text.encode("utf-8")
        if _HAS_DPAPI:
            try:
                blob = win32crypt.CryptProtectData(raw, "biliwb", None, None, None, 0)
                return DPAPI_PREFIX + blob
            except Exception:
                pass  # 落到 Fernet
        return FERNET_PREFIX + self._fernet().encrypt(raw)

    def unprotect(self, blob: bytes | None) -> str | None:
        if not blob:
            return None
        if isinstance(blob, memoryview):
            blob = bytes(blob)
        if blob.startswith(DPAPI_PREFIX):
            if not _HAS_DPAPI:
                raise RuntimeError("该凭证由 Windows DPAPI 加密，当前环境无法解密（需同机同用户）")
            return win32crypt.CryptUnprotectData(
                blob[len(DPAPI_PREFIX):], None, None, None, 0)[1].decode("utf-8")
        if blob.startswith(FERNET_PREFIX):
            return self._fernet().decrypt(blob[len(FERNET_PREFIX):]).decode("utf-8")
        # 无前缀：当明文处理（兼容手工写入）
        try:
            return blob.decode("utf-8")
        except Exception:
            raise RuntimeError("无法识别的密文格式")

    def describe(self) -> dict:
        return {
            "backend": self.backend,
            "note": ("Windows DPAPI：只有同机同用户可解"
                     if _HAS_DPAPI else
                     "Fernet 本机密钥文件：密钥路径 " + str(self.key_path)),
            "key_file_exists": self.key_path.exists(),
        }


def mask(text: str | None, keep: int = 4) -> str:
    """日志/报告里用的脱敏显示。"""
    if not text:
        return ""
    if len(text) <= keep:
        return "*" * len(text)
    return text[:keep] + "*" * min(12, len(text) - keep)

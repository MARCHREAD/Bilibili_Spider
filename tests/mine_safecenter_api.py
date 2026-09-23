"""扫描 passport JS，列出 /x/ 接口及其在代码里的绑定关系。

目标：拿到 status=2 短信验证流程要用的确切接口与参数
（captcha/pre → sms/send → 校验 → exchange_cookie）。

用法：python tests/mine_safecenter_api.py
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

DIRS = [
    ROOT / "tests" / "_riskverify" / "js",
    ROOT / "js_reverse_cache" / "tasks" / "bili-login-captcha" / "raw",
    ROOT / "js_reverse_cache" / "tasks" / "bili-login-captcha" / "raw" / "chunks",
]


def main() -> int:
    files: list[pathlib.Path] = []
    for d in DIRS:
        if d.is_dir():
            files += [p for p in d.rglob("*.js") if p.is_file()]
    print(f"扫描 {len(files)} 个 JS 文件", flush=True)

    paths: dict[str, set[str]] = {}
    bindings: list[tuple[str, str, str]] = []

    for p in files:
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        for m in re.finditer(r"[\"'](/x/[a-zA-Z0-9_\-/]{3,90})[\"']", t):
            paths.setdefault(m.group(1), set()).add(p.name)
        # 形如  name=t=>(0,n.XX)("/x/....",t)   或   name=function(){...("/x/..",t)}
        for m in re.finditer(
                r"([A-Za-z_$][\w$]{0,4})\s*=\s*(?:t|function\s*\([^)]*\))\s*(?:=>)?[^;{}]{0,120}?"
                r"[\"'](/x/[a-zA-Z0-9_\-/]{3,90})[\"']", t):
            bindings.append((p.name, m.group(1), m.group(2)))

    print(f"\n== 全部 /x/ 路径（{len(paths)} 个）==")
    for k in sorted(paths):
        src = ",".join(sorted(paths[k])[:3])
        print(f"  {k:<58} [{src}]")

    print(f"\n== 变量绑定（{len(bindings)} 条）==")
    seen = set()
    for f, name, path in bindings:
        key = (name, path)
        if key in seen:
            continue
        seen.add(key)
        print(f"  {name:<6} -> {path:<56} ({f})")

    out = ROOT / "tests" / "_riskverify" / "api_map.json"
    out.write_text(json.dumps(
        {"paths": {k: sorted(v) for k, v in paths.items()},
         "bindings": [{"file": f, "name": n, "path": p} for f, n, p in bindings]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n已写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

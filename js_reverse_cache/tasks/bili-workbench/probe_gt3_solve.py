"""实测 GT3 解算桥接：能否拿到可直接用于密码登录的 validate/challenge/token。"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import gt3  # noqa: E402


def main() -> int:
    ready = gt3.solver_ready()
    print(f"ready={ready['ready']} node={ready.get('node_version')}", file=sys.stderr)
    if not ready["ready"]:
        print(json.dumps(ready, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    print("开始解算（约 30~60 秒）...", file=sys.stderr)
    res = gt3.solve_once(timeout=900)
    for key in ("ok", "gt", "challenge", "token", "validate", "seccode",
                "score", "rounds_seen", "seconds", "error", "verdict"):
        if key in res:
            print(f"  {key} = {res[key]}", file=sys.stderr)
    for line in res.get("log_tail") or []:
        print(f"    | {line[:150]}", file=sys.stderr)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

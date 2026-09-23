"""End-to-end production check: run AccountPool.login_password on a real account.

Prints the structured result (credentials themselves are never printed).

Usage: python tests/e2e_login.py [account_id] [--attempts 2]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb.accounts import SOLVE_BUDGET_S, AccountPool
from biliwb.store import Store


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("account_id", nargs="?", type=int)
    ap.add_argument("--attempts", type=int, default=2)
    ap.add_argument("--budget", type=float, default=SOLVE_BUDGET_S)
    args = ap.parse_args()

    data_dir = ROOT / "data"
    store = Store(data_dir / "biliwb.db")
    pool = AccountPool(store, data_dir=data_dir)

    accounts = store.list_accounts()
    print("accounts:", [(a["id"], a["alias"], a["login_method"],
                         bool(a.get("password_enc")), a.get("last_status"))
                        for a in accounts])
    target = args.account_id
    if target is None:
        pw = [a for a in accounts if a.get("password_enc")]
        if not pw:
            print("没有存了密码的账号")
            return 2
        target = pw[0]["id"]

    acc = store.get_account(target)
    if not acc:
        print("账号不存在:", target)
        return 2
    pw = pool.box.unprotect(acc.get("password_enc"))
    print(f"target={target} alias={acc['alias']} username={acc.get('username')} "
          f"password_decrypt_ok={bool(pw)} password_len={len(pw or '')} "
          f"security={json.dumps(pool.describe_security(), ensure_ascii=False)}")

    print(f"--- running login_password(attempts={args.attempts}, budget={args.budget}s) ---",
          flush=True)
    res = pool.login_password(target, attempts=args.attempts, gt3_timeout=int(args.budget))
    safe = {k: v for k, v in res.items() if k not in ("attempt_history",)}
    print(json.dumps(safe, ensure_ascii=False, indent=2, default=str))
    if res.get("attempt_history"):
        print("--- attempt history ---")
        print(json.dumps(res["attempt_history"], ensure_ascii=False, indent=2, default=str))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

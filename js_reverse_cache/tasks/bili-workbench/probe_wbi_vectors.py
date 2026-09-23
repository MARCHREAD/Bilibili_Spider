"""WBI fixed-input parity 校验（离线，无 egress）。

输入：js_reverse_cache/tasks/bili-workbench/fixtures/wbi_vectors.json
      —— 这些 URL 是 live 页面自己发出的真实请求（initScript XHR hook 捕获）。

证明：用我方纯 Python 实现对同一组参数复算 w_rid，看是否等于页面生成值。

用法：python probe_wbi_vectors.py
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3]))

from biliwb import wbi  # noqa: E402

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "wbi_vectors.json"


def main() -> int:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    keys = data["candidate_keys"]
    vectors = data["vectors"]

    print(f"vectors: {len(vectors)}   candidate keys: {list(keys)}")
    overall = {}
    for key_name, key in keys.items():
        ok = 0
        detail = []
        for vec in vectors:
            match, got = wbi.verify_vector(vec["url"], key["img_key"], key["sub_key"])
            want = wbi.parse_query(vec["url"]).get("w_rid", "")
            ok += match
            detail.append(f"    {'OK  ' if match else 'FAIL'} {vec['name']:<18} want={want[:12]} got={got[:12]}")
        overall[key_name] = ok
        print(f"\n[{key_name}] {ok}/{len(vectors)} matched")
        print("\n".join(detail))

    winner = max(overall, key=overall.get)
    best = overall[winner]
    print(f"\nmixin_key sample for {winner}: {wbi.get_mixin_key(keys[winner]['img_key'] + keys[winner]['sub_key'])[:8]}...")
    if best == len(vectors):
        print(f"RESULT: PASS - full parity {best}/{len(vectors)} with {winner}")
        return 0
    print(f"RESULT: FAIL - best {best}/{len(vectors)} with {winner}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

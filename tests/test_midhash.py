"""midHash 算法回归（离线，不联网）。

固定向量来自 live 取证：
  js_reverse_cache/tasks/bili-workbench/fixtures/midhash_pairs.json

取证方法：对 15 个视频分别收集
  * 候选 uid 池 = 视频 UP 主 mid + 评论区（含二级）作者 mid
  * 弹幕 midHash 池 = XML `x/v1/dm/list.so` 的全量弹幕 midHash
然后跨视频求交。因为 midHash 只是 uid 的函数（与视频无关），
跨视频的 (uid, midHash) 命中仍是真实配对。

实测：池 415 uid × 18084 midHash，随机碰撞期望 ≈ 1.75e-03；
`crc32(str(uid))` 命中 47 个真实配对，另外 6 个候选（含双重 CRC32 加盐）全部 0 命中。

用法：python tests/test_midhash.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
import zlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb.api.danmaku import mid_hash_of  # noqa: E402

FIXTURE = ROOT / "js_reverse_cache" / "tasks" / "bili-workbench" / "fixtures" / "midhash_pairs.json"
SALT = "DU8tF3z6"


def c32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


REJECTED = {
    "双重 CRC32 + 盐": lambda m: f"{c32((str(c32(str(m).encode())) + SALT).encode()):08x}",
    "crc32(str+盐)": lambda m: f"{c32((str(m) + SALT).encode()):08x}",
    "crc32(盐+str)": lambda m: f"{c32((SALT + str(m)).encode()):08x}",
    "crc32(str(crc32))": lambda m: f"{c32(str(c32(str(m).encode())).encode()):08x}",
    "md5 前 8 位": lambda m: hashlib.md5(str(m).encode()).hexdigest()[:8],
    "crc32(8 字节整数)": lambda m: f"{c32(int(m).to_bytes(8, 'big')):08x}",
}


def main() -> int:
    if not FIXTURE.exists():
        print(f"缺少固定向量: {FIXTURE}", file=sys.stderr)
        return 2
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    pairs = [(int(p["uid"]), p["mid_hash"]) for p in data["pairs"]]
    passed = failed = 0

    print(f"固定向量: {len(pairs)} 对真实 (uid, midHash)")
    print(f"取证规模: 池 {data['pool_size']} uid × {data['hash_pool_size']} midHash, "
          f"随机碰撞期望 {data['random_collision_expectation']:.2e}")

    good = sum(1 for uid, h in pairs if mid_hash_of(uid) == h)
    if good == len(pairs):
        passed += 1
        print(f"  OK   crc32(str(uid)) 复现全部 {good}/{len(pairs)} 个配对")
    else:
        failed += 1
        bad = [(u, h, mid_hash_of(u)) for u, h in pairs if mid_hash_of(u) != h][:3]
        print(f"  FAIL 仅复现 {good}/{len(pairs)}，反例 {bad}")

    for name, fn in REJECTED.items():
        hits = sum(1 for uid, h in pairs if fn(uid) == h)
        if hits == 0:
            passed += 1
            print(f"  OK   负对照: {name} 命中 {hits}/{len(pairs)}")
        else:
            failed += 1
            print(f"  FAIL 负对照 {name} 竟然命中 {hits}")

    sample = [1, 2, 12345, 494757969, 3494366052091972]
    uniq = len({mid_hash_of(u) for u in sample})
    if uniq == len(sample):
        passed += 1
        print(f"  OK   不同 uid 产出不同 midHash（{uniq}/{len(sample)}）")
    else:
        failed += 1
        print("  FAIL uid 之间出现哈希碰撞")

    if mid_hash_of(1) == mid_hash_of(2):
        failed += 1
        print("  FAIL 边界失败")
    else:
        passed += 1
        print("  OK   边界: 相邻 uid 不碰撞")

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

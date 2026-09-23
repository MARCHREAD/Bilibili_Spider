"""持久化 midHash 字典的离线回归测试（纯 SQLite，不联网）。

背景：midHash = crc32(str(uid)) 与视频无关，所以一旦确认一对 (midHash, uid)
就可以在所有视频里复用。实测：第二轮完全不建候选池（只剩 UP 主），靠字典仍
认出 63 条弹幕，其中某视频第一轮 0 命中、第二轮字典认出 3 条。

用法：python tests/test_midhash_index.py
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb.store import MidHashIndex, Store  # noqa: E402

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label} {detail}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        store = Store(pathlib.Path(tmp) / "t.db")
        idx = MidHashIndex(store)

        print("[1] 写入与查询往返")
        n = store.midhash_remember([
            {"mid_hash": "9590c386", "uid": 104924180, "source": "pool"},
            {"mid_hash": "f251828e", "uid": 200670273, "uname": "某人", "level": 6,
             "source": "acc_info"},
        ])
        check("写入 2 条", n == 2, str(n))
        got = store.midhash_lookup({"9590c386", "f251828e", "notexist"})
        check("命中 2 条", len(got) == 2, str(list(got)))
        check("uid 正确", got["9590c386"]["uid"] == 104924180)
        check("uname/level 保留", got["f251828e"]["uname"] == "某人"
              and got["f251828e"]["level"] == 6)
        check("未收录的 hash 不返回", "notexist" not in got)

        print("[2] 幂等与字段合并")
        store.midhash_remember([{"mid_hash": "9590c386", "uid": 104924180,
                                 "uname": "补上名字", "level": 5, "source": "acc_info"}])
        again = store.midhash_lookup({"9590c386"})["9590c386"]
        check("重复写入不产生新行", store.stats()["midhash_index"] == 2,
              str(store.stats()["midhash_index"]))
        check("uname 被补齐", again["uname"] == "补上名字")
        check("level 被补齐", again["level"] == 5)
        store.midhash_remember([{"mid_hash": "9590c386", "uid": 104924180,
                                 "source": "pool"}])
        after = store.midhash_lookup({"9590c386"})["9590c386"]
        check("不带 uname 的更新不会清空已有值", after["uname"] == "补上名字",
              str(after))

        print("[3] 命中计数")
        for _ in range(3):
            store.midhash_lookup({"9590c386"})
        top = {r["mid_hash"]: r for r in store.midhash_top(10)}
        check("hits 递增", top["9590c386"]["hits"] >= 4, str(top["9590c386"]["hits"]))

        print("[4] 非法与边界输入")
        check("空输入不写入", store.midhash_remember([]) == 0)
        check("空查询返回空", store.midhash_lookup(set()) == {})
        check("缺 uid 的条目被跳过",
              store.midhash_remember([{"mid_hash": "x"}, {"uid": 1}]) == 0)
        check("uid 非法被跳过",
              store.midhash_remember([{"mid_hash": "y", "uid": "abc"}]) == 0)
        check("uid 字符串可接受",
              store.midhash_remember([{"mid_hash": "z1", "uid": "42"}]) == 1)
        check("字符串 uid 归一为 int",
              store.midhash_lookup({"z1"})["z1"]["uid"] == 42)

        print("[5] 分块查询（超过 400 条也不出错）")
        bulk = [{"mid_hash": f"{i:08x}", "uid": 1_000_000 + i} for i in range(900)]
        store.midhash_remember(bulk)
        many = store.midhash_lookup({f"{i:08x}" for i in range(900)})
        check("900 条全部命中", len(many) == 900, str(len(many)))

        store.close()

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

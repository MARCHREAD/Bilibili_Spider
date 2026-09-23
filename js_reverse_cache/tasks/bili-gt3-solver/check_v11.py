"""Offline check of gt3_click_solve_v11 against rounds whose answer we know by eye.

usage: python check_v11.py
"""
from __future__ import annotations

import json
import pathlib
import sys

import gt3_click_solve_v11 as v11

TASK = pathlib.Path(__file__).resolve().parent

# (image, prompt, {char: (x, y) of the glyph that must be clicked, in prompt order})
CASES = [
    {
        "pic": "cache/live2.jpg",
        "prompt": "黄包",
        "expect": [(195, 185), (290, 63)],          # 黄(Labelled tilted) then 包
    },
    {
        "pic": "cache/proto_20260921-200924/pic_7.jpg",
        "prompt": "爆炒田鸡",
        "expect": [(87, 289), (128, 140), (191, 36), (231, 246)],   # 爆 炒 田 鸡
    },
    {
        "pic": "cache/proto_20260921-200053/pic_7.jpg",
        "prompt": "炸茄盒",
        "expect": [(40, 185), (165, 39), (108, 162)],               # 炸 茄 盒
    },
    {
        "pic": "cache/live.jpg",
        "prompt": "鸡豆冰粉",
        "expect": [(93, 237), (272, 216), (157, 121), (81, 130)],   # 鸡 豆 冰 粉
    },
]


def near(a, b, tol=30):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def main() -> int:
    ok_all = True
    for case in CASES:
        pic = TASK / case["pic"]
        if not pic.exists():
            print(f"[skip] {case['pic']} missing")
            continue
        try:
            res = v11.solve(pic)
        except Exception as exc:  # noqa: BLE001
            print(f"[err ] {case['pic']}: {exc}")
            ok_all = False
            continue
        got = [tuple(p) for p in res.get("click_points") or []]
        exp = case["expect"]
        good = len(got) == len(exp) and all(near(g, e) for g, e in zip(got, exp))
        ok_all &= good
        print(f"[{'PASS' if good else 'FAIL'}] {case['pic']}")
        print(f"        prompt read={res.get('prompt_chars')} expected={list(case['prompt'])}")
        print(f"        boxes={res.get('field_boxes')}")
        print(f"        got={got}")
        print(f"        exp={exp}")
        for j, r in enumerate(res.get("readings") or []):
            print(f"        glyph{j}: " + " ".join(f"{k}x{v}" for k, v in r))
    print("ALL PASS" if ok_all else "SOME FAILED")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())

"""用本地 ddddocr 读图（视觉后端限流时的降级路径，纯本地、不联网模型）。

对 UI 截图这类多行版面，ddddocr 的通用识别只适合粗读；这里同时输出
按行切片的识别结果，尽量还原界面文字。

用法：python tests/ocr_local.py <image> [--rows N]
"""

from __future__ import annotations

import argparse
import pathlib
import sys

import cv2
import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--rows", type=int, default=0, help="切成 N 行分别识别（0=整图）")
    args = ap.parse_args()

    p = pathlib.Path(args.image)
    raw = np.frombuffer(p.read_bytes(), dtype=np.uint8)
    img = cv2.imdecode(raw, cv2.IMREAD_COLOR)
    if img is None:
        print("无法解码图片")
        return 2
    h, w = img.shape[:2]
    print(f"图片尺寸: {w}x{h}")

    import ddddocr
    ocr = ddddocr.DdddOcr(show_ad=False)

    def rec(sub) -> str:
        ok, buf = cv2.imencode(".png", sub)
        if not ok:
            return ""
        try:
            return ocr.classification(buf.tobytes())
        except Exception as exc:  # noqa: BLE001
            return f"<{type(exc).__name__}: {exc}>"

    print("--- 整图 ---")
    print(rec(img))

    if args.rows:
        print(f"--- 按 {args.rows} 行切片 ---")
        step = max(1, h // args.rows)
        for i in range(args.rows):
            y0 = i * step
            y1 = h if i == args.rows - 1 else min(h, y0 + step)
            band = img[y0:y1]
            # 放大有助于小字号识别
            band = cv2.resize(band, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            print(f"[y {y0:>4}-{y1:>4}] {rec(band)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

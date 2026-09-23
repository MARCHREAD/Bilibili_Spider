"""Experiment: can OCR identify a field glyph after de-rotation, and does IoU
discriminate better than v8's mean-closeness?
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve import find_prompt_box
from gt3_click_solve_dd import det_boxes, field_mask, prompt_mask
from gt3_click_solve_v6 import norm_height, rotate_mask

TASK = pathlib.Path(__file__).resolve().parent
PIC = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else TASK / "cache" / "proto_20260921-200053" / "pic_7.jpg"
ANG = list(range(0, 360, 10))


def rotate_img(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos) + 2, int(h * cos + w * sin) + 2
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_CUBIC,
                          borderMode=cv2.BORDER_REPLICATE)


def ocr(rec, img: np.ndarray, scale: int = 3) -> str:
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    ok, enc = cv2.imencode(".png", big)
    return rec.classification(enc.tobytes()) if ok else ""


def iou_score(p_mask: np.ndarray, f_mask: np.ndarray, height: int = 48):
    target = norm_height(f_mask, height)
    tb = (target > 0).astype(np.float32)
    b_ink = float(tb.sum()) or 1.0
    base = norm_height(p_mask, height)
    best = (0.0, 0)
    for angle in ANG:
        rot = rotate_mask(base, angle) if angle else base
        for s in (0.85, 1.0, 1.18):
            tpl = cv2.resize(rot, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST) if s != 1.0 else rot
            a_ink = float((tpl > 0).sum()) or 1.0
            ph, pw = max(tpl.shape[0], tb.shape[0]), max(tpl.shape[1], tb.shape[1])
            pad = np.zeros((ph, pw), np.float32)
            pad[:tb.shape[0], :tb.shape[1]] = tb
            res = cv2.matchTemplate(pad, tpl.astype(np.float32), cv2.TM_CCORR)
            inter = float(res.max()) / 255.0
            v = inter / (a_ink + b_ink - inter)
            if v > best[0]:
                best = (v, angle)
    return best


def main() -> int:
    import ddddocr
    img = cv2.imdecode(np.fromfile(str(PIC), dtype=np.uint8), cv2.IMREAD_COLOR)
    det = ddddocr.DdddOcr(det=True, show_ad=False)
    rec = ddddocr.DdddOcr(show_ad=False)
    px, py, pw, ph = find_prompt_box(img)
    card = img[py:py + ph, px:px + pw]
    p_boxes = sorted([b for b in det_boxes(det, card, scale=3.0) if b[2] >= 6 and b[3] >= 10], key=lambda b: b[0])
    field = img[:py, :]
    f_boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    p_masks = [prompt_mask(card[y:y + bh, x:x + bw]) for (x, y, bw, bh) in p_boxes]
    f_masks = [field_mask(field[y:y + bh, x:x + bw]) for (x, y, bw, bh) in f_boxes]
    p_chars = [ocr(rec, card[y:y + bh, x:x + bw]) for (x, y, bw, bh) in p_boxes]

    rep: dict = {"prompt_chars": p_chars, "field": [], "iou": []}
    print("prompt chars:", json.dumps(p_chars, ensure_ascii=True))

    for j, (x, y, bw, bh) in enumerate(f_boxes):
        crop = field[max(0, y - 3):y + bh + 3, max(0, x - 3):x + bw + 3]
        readings = {}
        for a in ANG:
            t = ocr(rec, rotate_img(crop, a))
            readings.setdefault(t, []).append(a)
        cjk = {k: v for k, v in readings.items() if len(k) == 1 and "\u4e00" <= k <= "\u9fff"}
        rep["field"].append({"box": [x, y, bw, bh], "cjk_readings": {k: v for k, v in cjk.items()},
                             "all": list(readings)[:14]})
        print(f"box{j} {x},{y}: cjk={json.dumps({k: v for k, v in cjk.items()}, ensure_ascii=True)} "
              f"other={json.dumps(list(readings)[:8], ensure_ascii=True)}")

    print("\nIoU matrix (rows=prompt char, cols=field glyph):")
    for i, pm in enumerate(p_masks):
        row = []
        for j, fm in enumerate(f_masks):
            v, a = iou_score(pm, fm)
            row.append(f"{v:.3f}@{a}")
        rep["iou"].append(row)
        print("  " + "  ".join(f"{c:>10}" for c in row))

    (TASK / "cache" / "exp_rot.json").write_text(json.dumps(rep, ensure_ascii=True, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

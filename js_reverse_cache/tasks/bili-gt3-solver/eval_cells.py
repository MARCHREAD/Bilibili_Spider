"""Evaluate: equal-split prompt cells + thin-stroke chamfer against neon brightness
masks.  Prints the score matrix for a round so we can check the argmax per prompt char.
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve_dd import det_boxes, note
from gt3_click_solve_v10 import is_cjk, ocr, prompt_card, rotate_img
from gt3_click_solve_v6 import norm_height, rotate_mask

TASK = pathlib.Path(__file__).resolve().parent
H = 56
ANG = list(range(0, 360, 5))


def val_mask(sub: np.ndarray, thr: int = 200) -> np.ndarray:
    hsv = cv2.cvtColor(sub, cv2.COLOR_BGR2HSV)
    m = (hsv[:, :, 2] > thr).astype(np.uint8) * 255
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))


def text_mask(sub: np.ndarray, thr: int = 110) -> np.ndarray:
    g = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
    m = (g < thr).astype(np.uint8) * 255
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    h, w = m.shape
    for i in range(1, n):
        x, y, ww, hh, area = stats[i]
        if area < 3 or x <= 1 or y <= 1 or x + ww >= w - 1 or y + hh >= h - 1:
            continue
        keep[lab == i] = 255
    return keep


def split_cells(mask: np.ndarray, n: int):
    cols = np.where((mask > 0).sum(axis=0) > 0)[0]
    rows = np.where((mask > 0).sum(axis=1) > 0)[0]
    x0, x1 = int(cols.min()), int(cols.max()) + 1
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    step = (x1 - x0) / float(n)
    return [mask[y0:y1, int(round(x0 + i * step)):int(round(x0 + (i + 1) * step))] for i in range(n)]


def sym_chamfer(pm: np.ndarray, fm: np.ndarray, scale_range=(0.85, 1.0, 1.15)):
    base = norm_height(pm, H)
    target = (norm_height(fm, H) > 0).astype(np.uint8)
    if target.sum() == 0 or base.sum() == 0:
        return 1e9, 0
    dt_t = cv2.distanceTransform(1 - target, cv2.DIST_L2, 3)
    best, best_a = 1e9, 0
    for a in ANG:
        rot = rotate_mask(base, a) if a else base
        for s in scale_range:
            tpl = cv2.resize(rot, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST) if s != 1.0 else rot
            ink = float((tpl > 0).sum()) or 1.0
            ph, pw = max(tpl.shape[0], dt_t.shape[0]), max(tpl.shape[1], dt_t.shape[1])
            pad = np.zeros((ph, pw), np.float32)
            pad[:dt_t.shape[0], :dt_t.shape[1]] = dt_t
            res = cv2.matchTemplate(pad, tpl.astype(np.float32), cv2.TM_CCORR)
            fwd = float(res.min()) / ink
            # backward: target ink to template ink at that offset
            off = np.unravel_index(int(res.argmin()), res.shape)
            ph2, pw2 = max(target.shape[0], tpl.shape[0]), max(target.shape[1], tpl.shape[1])
            tp = np.zeros((ph2, pw2), np.uint8)
            ox, oy = off[1], off[0]           # where the template sits inside the pad
            tp[oy:oy + tpl.shape[0], ox:ox + tpl.shape[1]] = (tpl > 0).astype(np.uint8)
            dt_p = cv2.distanceTransform(1 - tp, cv2.DIST_L2, 3)
            tgt = np.zeros((ph2, pw2), np.uint8)
            tgt[:target.shape[0], :target.shape[1]] = target
            bwd = float(dt_p[tgt > 0].mean()) if (tgt > 0).any() else 1e9
            v = (fwd + bwd) / 2.0
            if v < best:
                best, best_a = v, a
    return best, best_a


def main() -> int:
    pic = pathlib.Path(sys.argv[1])
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else TASK / "cache" / "cells_v2.png"
    import ddddocr
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    det = ddddocr.DdddOcr(det=True, show_ad=False)
    rec = ddddocr.DdddOcr(show_ad=False)
    card, box, src = prompt_card(img)
    field = img[:box[1], :]
    texts = [ocr(rec, card, s) for s in (2, 3, 6)]
    chars = [c for c in max(texts, key=len) if is_cjk(c)]
    n = len(chars)
    card_mask = text_mask(card)
    cells = split_cells(card_mask, n) if 2 <= n <= 6 else []
    print("card src:", src, "texts:", json.dumps(texts, ensure_ascii=True), "n:", n)

    f_boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    if f_boxes:
        medw = int(np.median([b[2] for b in f_boxes]))
        medh = int(np.median([b[3] for b in f_boxes]))
        f_boxes = [(x - max(0, (medw - bw) // 2), y - max(0, (medh - bh) // 2), max(bw, medw), max(bh, medh))
                   for (x, y, bw, bh) in f_boxes]
    f_masks = [val_mask(field[max(0, y):y + bh, max(0, x):x + bw]) for (x, y, bw, bh) in f_boxes]
    print("field boxes (size-normalised):", f_boxes)

    print("\nsymmetric chamfer (lower better):")
    for i, cm in enumerate(cells):
        row = [sym_chamfer(cm, fm)[0] for fm in f_masks]
        print(f"  P{i} '{chars[i]}' " + "  ".join(f"{v:5.2f}" for v in row)
              + f"   best=F{int(np.argmin(row))}")

    tiles = [(f"P{i}", norm_height(m, H)) for i, m in enumerate(cells)] + \
            [(f"F{j}", norm_height(m, H)) for j, m in enumerate(f_masks)]
    cw = max(t[1].shape[1] for t in tiles) + 12
    canvas = np.zeros((H + 30, cw * len(tiles), 3), np.uint8)
    for k, (lab, t) in enumerate(tiles):
        x = k * cw + 6
        canvas[2:2 + t.shape[0], x:x + t.shape[1]] = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
        cv2.putText(canvas, lab, (x, H + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    cv2.imencode(".png", canvas)[1].tofile(str(out))
    note(f"[montage] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

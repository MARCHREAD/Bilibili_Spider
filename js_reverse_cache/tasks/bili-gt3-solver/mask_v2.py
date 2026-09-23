"""Cleaner masks + a side-by-side evaluation of identification metrics.

field mask : the glyph strokes are thin neon lines over a photo, so a large-kernel
             median filter estimates the background and |img - med| isolates the
             strokes.  The old "distance from the box median colour" picked up whole
             textured patches of the photo.
prompt mask: the card is near-white with a near-black glyph; a strict threshold plus a
             border inset drops the card's border/shadow that used to connect every
             character into one blob.

usage: python mask_v2.py <pic.jpg> [out.png]
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve import find_prompt_box
from gt3_click_solve_dd import det_boxes, note
from gt3_click_solve_v6 import norm_height, rotate_mask

TASK = pathlib.Path(__file__).resolve().parent
H = 64
ANG = list(range(0, 360, 5))


def prompt_mask_v2(sub: np.ndarray, inset: int = 2, thr: int = 110) -> np.ndarray:
    """Black glyph on a white card -> strict dark threshold, border inset."""
    if inset:
        sub = sub[inset:-inset, inset:-inset] if sub.shape[0] > 2 * inset + 2 and sub.shape[1] > 2 * inset + 2 else sub
    gray = cv2.cvtColor(sub, cv2.COLOR_BGR2GRAY)
    mask = (gray < thr).astype(np.uint8) * 255
    # drop any component that hugs the crop border (card frame / shadow)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    keep = np.zeros_like(mask)
    h, w = mask.shape
    for i in range(1, n):
        x, y, ww, hh, area = stats[i]
        if area < 4:
            continue
        if x <= 0 or y <= 0 or x + ww >= w or y + hh >= h:
            continue
        keep[lab == i] = 255
    return cv2.morphologyEx(keep, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))


def field_mask_v2(sub: np.ndarray, k: int = 21, thr: float | None = None) -> np.ndarray:
    """Thin neon strokes over an arbitrary photo -> |img - median background|."""
    k = k if k % 2 == 1 else k + 1
    med = cv2.medianBlur(sub, k)
    d = np.linalg.norm(sub.astype(np.float32) - med.astype(np.float32), axis=2)
    if thr is None:
        t, _ = cv2.threshold(d.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        thr = max(28.0, float(t))
    mask = (d > thr).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return mask


def iou_best(pm: np.ndarray, fm: np.ndarray) -> tuple[float, int, float]:
    target = norm_height(fm, H)
    tb = (target > 0).astype(np.float32)
    b_ink = float(tb.sum()) or 1.0
    base = norm_height(pm, H)
    best, best_angle, best_scale = 0.0, 0, 1.0
    for angle in ANG:
        rot = rotate_mask(base, angle) if angle else base
        for s in (0.9, 1.0, 1.1):
            tpl = cv2.resize(rot, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST) if s != 1.0 else rot
            a_ink = float((tpl > 0).sum()) or 1.0
            ph, pw = max(tpl.shape[0], tb.shape[0]), max(tpl.shape[1], tb.shape[1])
            pad = np.zeros((ph, pw), np.float32)
            pad[:tb.shape[0], :tb.shape[1]] = tb
            res = cv2.matchTemplate(pad, tpl.astype(np.float32), cv2.TM_CCORR)
            inter = float(res.max()) / 255.0
            v = inter / (a_ink + b_ink - inter)
            if v > best:
                best, best_angle, best_scale = v, angle, s
    return best, best_angle, best_scale


def chamfer_best(pm: np.ndarray, fm: np.ndarray) -> tuple[float, int]:
    base = norm_height(pm, H)
    target = (norm_height(fm, H) > 0).astype(np.uint8)
    dt = cv2.distanceTransform(1 - target, cv2.DIST_L2, 3)
    best, best_angle = 1e9, 0
    for angle in ANG:
        rot = rotate_mask(base, angle) if angle else base
        for s in (0.9, 1.0, 1.1):
            tpl = cv2.resize(rot, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST) if s != 1.0 else rot
            ink = float((tpl > 0).sum()) or 1.0
            ph, pw = max(tpl.shape[0], dt.shape[0]), max(tpl.shape[1], dt.shape[1])
            pad = np.zeros((ph, pw), np.float32)
            pad[:dt.shape[0], :dt.shape[1]] = dt
            res = cv2.matchTemplate(pad, tpl.astype(np.float32), cv2.TM_CCORR)
            v = float(res.min()) / ink           # mean distance of template ink to target ink
            if v < best:
                best, best_angle = v, angle
    return best, best_angle


def main() -> int:
    pic = pathlib.Path(sys.argv[1])
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else TASK / "cache" / "mask_v2.png"
    import ddddocr
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    det = ddddocr.DdddOcr(det=True, show_ad=False)
    rec = ddddocr.DdddOcr(show_ad=False)
    px, py, pw, ph = find_prompt_box(img)
    card = img[py:py + ph, px:px + min(pw, 200)]
    text = rec.classification(cv2.imencode(".png", cv2.resize(card, None, fx=3, fy=3,
                                                              interpolation=cv2.INTER_CUBIC))[1].tobytes())
    p_boxes = sorted([b for b in det_boxes(det, card, scale=3.0) if b[2] >= 6 and b[3] >= 10], key=lambda b: b[0])
    field = img[:py, :]
    f_boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    p_masks = [prompt_mask_v2(card[y:y + bh, x:x + bw]) for (x, y, bw, bh) in p_boxes]
    f_masks = [field_mask_v2(field[y:y + bh, x:x + bw]) for (x, y, bw, bh) in f_boxes]

    print("prompt_text:", json.dumps(text, ensure_ascii=True))
    print("prompt_boxes:", p_boxes)
    print("field_boxes:", f_boxes)

    print("\nIoU (higher better):")
    for i in range(len(p_masks)):
        row = [iou_best(p_masks[i], f_masks[j]) for j in range(len(f_masks))]
        print(f"  P{i} " + "  ".join(f"{v[0]:.3f}@{v[1]:3d}/{v[2]:.2f}" for v in row)
              + "   best=F" + str(int(np.argmax([v[0] for v in row]))))
    print("\nchamfer (lower better):")
    for i in range(len(p_masks)):
        row = [chamfer_best(p_masks[i], f_masks[j]) for j in range(len(f_masks))]
        print(f"  P{i} " + "  ".join(f"{v[0]:5.2f}@{v[1]:3d}" for v in row)
              + "   best=F" + str(int(np.argmin([v[0] for v in row]))))

    tiles = [("P%d" % i, norm_height(m, H)) for i, m in enumerate(p_masks)] + \
            [("F%d" % j, norm_height(m, H)) for j, m in enumerate(f_masks)]
    pad = 12
    cw = max(t[1].shape[1] for t in tiles) + pad
    canvas = np.zeros((H + 48, cw * len(tiles), 3), np.uint8)
    for k, (label, m) in enumerate(tiles):
        x = k * cw + pad // 2
        canvas[8:8 + m.shape[0], x:x + m.shape[1]] = cv2.cvtColor(m, cv2.COLOR_GRAY2BGR)
        cv2.putText(canvas, label, (x, H + 36), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    cv2.imencode(".png", canvas)[1].tofile(str(out))
    note(f"[montage] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

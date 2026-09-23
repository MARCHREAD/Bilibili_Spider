"""Build a montage of normalised prompt/field masks so we can SEE whether the masks
are clean, and print several candidate similarity metrics side by side.

usage: python dbg_masks.py <pic.jpg> <out.png>
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
H = 64
ANG = list(range(0, 360, 5))


def chamfer_sym(a: np.ndarray, b: np.ndarray) -> tuple[float, int]:
    """Symmetric mean chamfer distance between two ink masks (lower is better)."""
    A = (a > 0).astype(np.uint8)
    B = (b > 0).astype(np.uint8)
    if A.sum() == 0 or B.sum() == 0:
        return 1e9, 0
    ph, pw = max(A.shape[0], B.shape[0]), max(A.shape[1], B.shape[1])
    pa = np.zeros((ph, pw), np.uint8); pa[:A.shape[0], :A.shape[1]] = A
    pb = np.zeros((ph, pw), np.uint8); pb[:B.shape[0], :B.shape[1]] = B
    dta = cv2.distanceTransform(1 - pa, cv2.DIST_L2, 3)
    dtb = cv2.distanceTransform(1 - pb, cv2.DIST_L2, 3)
    fwd = float(dta[pb > 0].mean()) if (pb > 0).any() else 1e9
    bwd = float(dtb[pa > 0].mean()) if (pa > 0).any() else 1e9
    return (fwd + bwd) / 2.0, 0


def best_chamfer(pm: np.ndarray, fm: np.ndarray) -> tuple[float, int]:
    base = norm_height(pm, H)
    target = norm_height(fm, H)
    best, best_a = 1e9, 0
    for a in ANG:
        rot = rotate_mask(base, a) if a else base
        for s in (0.9, 1.0, 1.1):
            tpl = cv2.resize(rot, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST) if s != 1.0 else rot
            v, _ = chamfer_sym(tpl, target)
            if v < best:
                best, best_a = v, a
    return best, best_a


def hu_sim(pm: np.ndarray, fm: np.ndarray) -> float:
    a = norm_height(pm, H)
    b = norm_height(fm, H)
    ha = cv2.HuMoments(cv2.moments((a > 0).astype(np.uint8) * 255)).flatten()
    hb = cv2.HuMoments(cv2.moments((b > 0).astype(np.uint8) * 255)).flatten()
    ha = -np.sign(ha) * np.log10(np.abs(ha) + 1e-30)
    hb = -np.sign(hb) * np.log10(np.abs(hb) + 1e-30)
    return float(1.0 / (1.0 + np.abs(ha - hb).sum()))


def main() -> int:
    pic = pathlib.Path(sys.argv[1])
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else TASK / "cache" / "dbg_masks.png"
    import ddddocr
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    det = ddddocr.DdddOcr(det=True, show_ad=False)
    rec = ddddocr.DdddOcr(show_ad=False)
    px, py, pw, ph = find_prompt_box(img)
    card = img[py:py + ph, px:px + min(pw, 200)]
    p_boxes = sorted([b for b in det_boxes(det, card, scale=3.0) if b[2] >= 6 and b[3] >= 10], key=lambda b: b[0])
    field = img[:py, :]
    f_boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    p_masks = [prompt_mask(card[y:y + bh, x:x + bw]) for (x, y, bw, bh) in p_boxes]
    f_masks = [field_mask(field[y:y + bh, x:x + bw]) for (x, y, bw, bh) in f_boxes]
    text = rec.classification(cv2.imencode(".png", cv2.resize(card, None, fx=3, fy=3,
                                                              interpolation=cv2.INTER_CUBIC))[1].tobytes())

    tiles = []
    for i, m in enumerate(p_masks):
        n = norm_height(m, H)
        tiles.append(("P%d" % i, n))
    for j, m in enumerate(f_masks):
        n = norm_height(m, H)
        tiles.append(("F%d" % j, n))

    pad = 10
    cw = max(t[1].shape[1] for t in tiles) + pad
    canvas = np.zeros((H + 46, cw * len(tiles), 3), np.uint8)
    for k, (label, m) in enumerate(tiles):
        x = k * cw + pad // 2
        canvas[8:8 + m.shape[0], x:x + m.shape[1]] = cv2.cvtColor(m, cv2.COLOR_GRAY2BGR)
        cv2.putText(canvas, label, (x, H + 34), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
    cv2.imencode(".png", canvas)[1].tofile(str(out))

    print("prompt_text:", json.dumps(text, ensure_ascii=True))
    print("prompt boxes:", p_boxes)
    print("field boxes:", f_boxes)
    print("\nchamfer (lower=better):")
    for i in range(len(p_masks)):
        row = []
        for j in range(len(f_masks)):
            v, a = best_chamfer(p_masks[i], f_masks[j])
            row.append(f"{v:6.2f}@{a:3d}")
        print("  " + "  ".join(row))
    print("\nhu-moment sim (higher=better):")
    for i in range(len(p_masks)):
        row = [f"{hu_sim(p_masks[i], f_masks[j]):.3f}" for j in range(len(f_masks))]
        print("  " + "  ".join(row))
    print(f"\n[montage] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

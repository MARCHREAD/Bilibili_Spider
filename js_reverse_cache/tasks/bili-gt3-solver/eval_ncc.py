"""Edge-map NCC matching test.

The prompt glyphs are black on white and the field glyphs are neon outlines, so pixel
masks and chamfer distances keep failing.  Gradient orientation, however, is (nearly)
independent of colour and stroke fill, so compare the two as EDGE MAPS with
TM_CCOEFF_NORMED over a rotation/scale sweep.
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve_v10 import is_cjk, ocr, prompt_card, rotate_img
from gt3_click_solve_v6 import norm_height, rotate_mask

TASK = pathlib.Path(__file__).resolve().parent
H = 64
ANG = list(range(0, 360, 5))
SCALES = (0.8, 0.9, 1.0, 1.1, 1.25)


def edge_map(gray: np.ndarray) -> np.ndarray:
    g = cv2.GaussianBlur(gray, (3, 3), 0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)
    mag = cv2.normalize(mag, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    _, e = cv2.threshold(mag, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return e


def prep(gray: np.ndarray) -> np.ndarray:
    e = edge_map(gray)
    n = norm_height(e, H)
    return n


def ncc_best(pm: np.ndarray, fm: np.ndarray) -> tuple[float, int, float]:
    """Best normalised correlation of prompt edge map inside the field edge map."""
    tpl0 = (pm > 0).astype(np.float32)
    tgt0 = (fm > 0).astype(np.float32)
    if tpl0.sum() < 10 or tgt0.sum() < 10:
        return -1.0, 0, 1.0
    # pad the target so every rotation of the template can still be placed
    pad = max(tpl0.shape) + 6
    canvas = np.zeros((tgt0.shape[0] + 2 * pad, tgt0.shape[1] + 2 * pad), np.float32)
    canvas[pad:pad + tgt0.shape[0], pad:pad + tgt0.shape[1]] = tgt0
    best, best_a, best_s = -1.0, 0, 1.0
    for a in ANG:
        rot = rotate_mask((tpl0 * 255).astype(np.uint8), a) if a else (tpl0 * 255).astype(np.uint8)
        for s in SCALES:
            t = cv2.resize(rot, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST) if s != 1.0 else rot
            t = (t > 0).astype(np.float32)
            if t.shape[0] >= canvas.shape[0] or t.shape[1] >= canvas.shape[1] or t.sum() < 10:
                continue
            try:
                res = cv2.matchTemplate(canvas, t, cv2.TM_CCOEFF_NORMED)
            except cv2.error:
                continue
            v = float(res.max())
            if v > best:
                best, best_a, best_s = v, a, s
    return best, best_a, best_s


def main() -> int:
    pic = pathlib.Path(sys.argv[1])
    out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else TASK / "cache" / "ncc.png"
    import ddddocr
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    det = ddddocr.DdddOcr(det=True, show_ad=False)
    rec = ddddocr.DdddOcr(show_ad=False)
    card, box, src = prompt_card(img)
    field = img[:box[1], :]
    texts = [ocr(rec, card, s) for s in (2, 3, 6)]
    chars = [c for c in max(texts, key=len) if is_cjk(c)]
    n = len(chars)

    # equal split of the card's ink span
    g = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    cm = (g < 130).astype(np.uint8) * 255
    cols = np.where(cm.sum(axis=0) > 0)[0]
    rows = np.where(cm.sum(axis=1) > 0)[0]
    x0, x1 = int(cols.min()), int(cols.max()) + 1
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    step = (x1 - x0) / float(n)
    print(f"card={src} chars={json.dumps(chars, ensure_ascii=True)} ink_span=({x0},{y0})-({x1},{y1})")

    p_maps = []
    for i in range(n):
        a = int(round(x0 + i * step)); b = int(round(x0 + (i + 1) * step))
        cell = card[y0:y1, max(a - 2, 0):min(b + 2, card.shape[1])]
        p_maps.append(prep(cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)))
        print(f"  cell{i} x={a}..{b} ink={int((cm[y0:y1, a:b] > 0).sum())}")

    # field glyph boxes: detector boxes expanded to the median size
    f_boxes = [b for b in __import__("gt3_click_solve_dd", fromlist=["det_boxes"]).det_boxes(det, field)
               if b[2] >= 15 and b[3] >= 15]
    if f_boxes:
        mw = int(np.median([b[2] for b in f_boxes])); mh = int(np.median([b[3] for b in f_boxes]))
        f_boxes = [(max(0, x - (mw - bw) // 2), max(0, y - (mh - bh) // 2), max(bw, mw), max(bh, mh))
                   for (x, y, bw, bh) in f_boxes]
    f_maps = [prep(cv2.cvtColor(field[cv2.boundingRect(np.array([[x, y, bw, bh]]))[1] if False else y:
                                      y + bh, x:x + bw], cv2.COLOR_BGR2GRAY)) for (x, y, bw, bh) in f_boxes]
    print("field boxes:", f_boxes)

    print("\nedge NCC (higher better):")
    matrix = []
    for i in range(n):
        row = [ncc_best(p_maps[i], fm)[0] for fm in f_maps]
        matrix.append(row)
        print(f"  P{i} '{chars[i]}' " + "  ".join(f"{v:6.3f}" for v in row)
              + f"   best=F{int(np.argmax(row))}")

    tiles = [(f"P{i}", p_maps[i]) for i in range(n)] + [(f"F{j}", fm) for j, fm in enumerate(f_maps)]
    cw = max(t[1].shape[1] for t in tiles) + 12
    canvas = np.zeros((H + 30, cw * len(tiles), 3), np.uint8)
    for k, (lab, t) in enumerate(tiles):
        x = k * cw + 6
        canvas[2:2 + t.shape[0], x:x + t.shape[1]] = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
        cv2.putText(canvas, lab, (x, H + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    cv2.imencode(".png", canvas)[1].tofile(str(out))
    print("[montage]", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

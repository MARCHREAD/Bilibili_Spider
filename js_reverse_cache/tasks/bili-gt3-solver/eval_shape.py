"""Shape-matching evaluation with masks built the right way round.

Previous attempts failed for a silly reason: the prompt cells were cut with the ink
splitting and THEN components touching the cell border were discarded as "card frame",
which deleted most strokes of every glyph.  Here the whole card is masked first (and
only the full card's border components are dropped), then the mask is cut into cells.

usage: python eval_shape.py <pic.jpg>            # field crops from detector boxes
       python eval_shape.py <pic.jpg> --centres "87,289;128,140;..."
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve_v10 import is_cjk, ocr, prompt_card
from gt3_click_solve_v6 import norm_height, rotate_mask

TASK = pathlib.Path(__file__).resolve().parent
H = 64
ANG = list(range(0, 360, 5))
SCALES = (0.85, 0.95, 1.05, 1.15)


def card_mask(card: np.ndarray, thr: int = 130) -> np.ndarray:
    g = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    m = (g < thr).astype(np.uint8) * 255
    m[:1, :] = 0; m[-1:, :] = 0; m[:, :1] = 0; m[:, -1:] = 0
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    for i in range(1, n):
        area = stats[i][4]
        if area >= 4:
            keep[lab == i] = 255
    return keep


def split_columns(mask: np.ndarray, n: int, gap_ratio: float = 0.35) -> list[np.ndarray]:
    """Cut the mask into n cells.

    The card lays its characters out evenly, so equal division of the ink span is the
    reliable rule; the local-minimum search below only *refines* it when a clear empty
    column sits within +-30% of the equal boundary (it used to pick a cut at the very
    start of the span and hand back an empty first cell).
    """
    cols = (mask > 0).sum(axis=0)
    nz = np.where(cols > 0)[0]
    if len(nz) == 0 or n < 1:
        return []
    x0, x1 = int(nz.min()), int(nz.max()) + 1
    rows = np.where((mask > 0).sum(axis=1) > 0)[0]
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    if n == 1:
        return [mask[y0:y1, x0:x1]]
    span = max(1, x1 - x0)
    bounds = [x0]
    for k in range(1, n):
        guess = x0 + span * k / n
        win = max(3, int(span * 0.3 / n))
        lo, hi = int(max(x0 + 1, guess - win)), int(min(x1 - 1, guess + win))
        if hi > lo:
            seg = cols[lo:hi + 1]
            cut = lo + int(np.argmin(seg)) if seg.min() <= max(1, int(seg.max() * gap_ratio)) else int(round(guess))
        else:
            cut = int(round(guess))
        bounds.append(cut)
    bounds.append(x1)
    bounds = sorted(set(bounds))
    return [mask[y0:y1, bounds[i]:bounds[i + 1]] for i in range(len(bounds) - 1)]


def stroke_mask(crop: np.ndarray, k: int = 21, mult: float = 1.25) -> np.ndarray:
    med = cv2.medianBlur(crop, k)
    d = np.linalg.norm(crop.astype(np.float32) - med.astype(np.float32), axis=2)
    t, _ = cv2.threshold(d.astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    m = ((d > max(26.0, t * mult)).astype(np.uint8)) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
    keep = np.zeros_like(m)
    for i in range(1, n):
        if stats[i][4] >= 12:
            keep[lab == i] = 255
    return keep


def chamfer(pm: np.ndarray, fm: np.ndarray) -> tuple[float, int, float]:
    """Symmetric mean chamfer over rotation+scale (lower is better).

    Correlation is done with filter2D(anchor=(0,0)) instead of matchTemplate: OpenCV's
    TM_CCORR path asserts img <= templ (it slides the *image* over the template), which
    is the opposite of what we need here.
    """
    base = norm_height(pm, H)
    target = (norm_height(fm, H) > 0).astype(np.uint8)
    if target.sum() < 20 or base.sum() < 20:
        return 1e9, 0, 1.0
    dt_t = cv2.distanceTransform(1 - target, cv2.DIST_L2, 3)
    best, best_a, best_s = 1e9, 0, 1.0
    for a in ANG:
        rot = rotate_mask(base, a) if a else base
        for s in SCALES:
            tpl = cv2.resize(rot, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST) if s != 1.0 else rot
            th, tw = tpl.shape
            ink = float((tpl > 0).sum()) or 1.0
            pad = np.full((dt_t.shape[0] + th, dt_t.shape[1] + tw), 1e4, np.float32)
            pad[:dt_t.shape[0], :dt_t.shape[1]] = dt_t
            resp = cv2.filter2D(pad, cv2.CV_32F, tpl.astype(np.float32), anchor=(0, 0),
                                borderType=cv2.BORDER_CONSTANT)
            v = float(resp.min()) / ink
            if v < best:
                best, best_a, best_s = v, a, s
    return best, best_a, best_s


def main() -> int:
    pic = pathlib.Path(sys.argv[1])
    centres = None
    if "--centres" in sys.argv:
        centres = [tuple(int(v) for v in c.split(",")) for c in sys.argv[sys.argv.index("--centres") + 1].split(";")]
    import ddddocr
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    det = ddddocr.DdddOcr(det=True, show_ad=False)
    rec = ddddocr.DdddOcr(show_ad=False)
    card, box, src = prompt_card(img)
    field = img[:box[1], :]
    texts = [ocr(rec, card, s) for s in (2, 3, 4, 6)]
    chars = [c for c in max(texts, key=len) if is_cjk(c)]
    n = len(chars)
    cm = card_mask(card)
    cells = split_columns(cm, n)
    print(f"card={src} text={json.dumps(texts, ensure_ascii=True)} n={n}")

    if centres:
        f_masks, f_labels = [], []
        for (cx, cy) in centres:
            c = field[max(0, cy - 44):cy + 44, max(0, cx - 44):cx + 44]
            f_masks.append(stroke_mask(c)); f_labels.append(f"{cx},{cy}")
    else:
        from gt3_click_solve_dd import det_boxes
        fb = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
        mw = int(np.median([b[2] for b in fb])); mh = int(np.median([b[3] for b in fb]))
        f_masks, f_labels = [], []
        for (x, y, bw, bh) in fb:
            x = max(0, x - (mw - bw) // 2); y = max(0, y - (mh - bh) // 2)
            bw, bh = max(bw, mw), max(bh, mh)
            f_masks.append(stroke_mask(field[y:y + bh, x:x + bw])); f_labels.append(f"{x},{y}")
    print("field:", f_labels)

    print("\nsymmetric chamfer (lower better):")
    for i, cell in enumerate(cells):
        row = [chamfer(cell, fm)[0] for fm in f_masks]
        print(f"  P{i} '{chars[i]}' " + "  ".join(f"{v:6.2f}" for v in row)
              + f"   best=F{int(np.argmin(row))}")

    tiles = [(f"P{i}", norm_height(cells[i], H)) for i in range(len(cells))] + \
            [(f"F{j}", norm_height(f_masks[j], H)) for j in range(len(f_masks))]
    cw = max(t[1].shape[1] for t in tiles) + 12
    canvas = np.zeros((H + 34, cw * len(tiles), 3), np.uint8)
    for k, (lab, t) in enumerate(tiles):
        x = k * cw + 6
        canvas[2:2 + t.shape[0], x:x + t.shape[1]] = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
        cv2.putText(canvas, lab, (x, H + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    out = TASK / "cache" / "eval_shape.png"
    cv2.imencode(".png", canvas)[1].tofile(str(out))
    print("[montage]", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

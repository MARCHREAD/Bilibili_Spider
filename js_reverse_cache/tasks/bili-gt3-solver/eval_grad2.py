"""Glyph matching v2: centroid-normalised gradient maps + translation-tolerant NCC.

Fixes the 0/0 problem of the first attempt: the search canvas was zero-padded, so a
window that was entirely padding had zero variance and TM_CCOEFF_NORMED produced
NaN/1.0.  Here both glyphs are first cropped to their strong-gradient bounding box,
scaled to a common height and pasted centred into a fixed canvas, so the template is
always strictly smaller than the search image and no padding window is ever constant.
"""
from __future__ import annotations

import json
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve_v10 import is_cjk, ocr, prompt_card

TASK = pathlib.Path(__file__).resolve().parent
OUT = 96          # canvas size for the search image
TPL_H = 52        # template height
ANG = list(range(0, 360, 5))
SCALES = (0.8, 0.9, 1.0, 1.12, 1.25)


def grad_mag(bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    g = cv2.GaussianBlur(gray, (3, 3), 0)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.magnitude(gx, gy)


def norm_canvas(bgr: np.ndarray, canvas: int = OUT, tpl_h: int = TPL_H) -> np.ndarray:
    """Gradient map -> bbox of strong gradient -> scaled -> centred on a canvas."""
    m = grad_mag(bgr)
    if m.size == 0:
        return np.zeros((canvas, canvas), np.float32)
    thr = float(m.mean() + 0.8 * m.std())
    ys, xs = np.where(m > thr)
    if len(xs) < 4:
        ys, xs = np.where(m > m.mean())
    if len(xs) < 4:
        return np.zeros((canvas, canvas), np.float32)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    crop = m[y0:y1, x0:x1]
    s = tpl_h / max(1, crop.shape[0])
    small = cv2.resize(crop, (max(2, int(round(crop.shape[1] * s))), tpl_h), interpolation=cv2.INTER_AREA)
    out = np.zeros((canvas, canvas), np.float32)
    oy = max(0, (canvas - small.shape[0]) // 2)
    ox = max(0, (canvas - small.shape[1]) // 2)
    h = min(small.shape[0], canvas - oy); w = min(small.shape[1], canvas - ox)
    out[oy:oy + h, ox:ox + w] = small[:h, :w]
    return out


def rot(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def ncc(pm: np.ndarray, fm: np.ndarray) -> tuple[float, int, float]:
    if pm.std() < 1e-6 or fm.std() < 1e-6:
        return -1.0, 0, 1.0
    best, best_a, best_s = -1.0, 0, 1.0
    tgt = fm.astype(np.float32)
    for a in ANG:
        r = rot(pm, a) if a else pm
        for s in SCALES:
            t = cv2.resize(r, None, fx=s, fy=s, interpolation=cv2.INTER_LINEAR) if s != 1.0 else r
            th, tw = t.shape
            if th >= tgt.shape[0] or tw >= tgt.shape[1] or t.std() < 1e-6:
                continue
            res = cv2.matchTemplate(tgt, t, cv2.TM_CCOEFF_NORMED)
            if not np.isfinite(res).any():
                continue
            v = float(np.nanmax(res))
            if v > best:
                best, best_a, best_s = v, a, s
    return best, best_a, best_s


def prompt_cells(card: np.ndarray, n: int, thr: int = 140):
    g = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    cm = (g < thr).astype(np.uint8) * 255
    cm[:1, :] = 0; cm[-1:, :] = 0; cm[:, :1] = 0; cm[:, -1:] = 0
    cols = np.where((cm > 0).sum(axis=0) > 0)[0]
    rows = np.where((cm > 0).sum(axis=1) > 0)[0]
    x0, x1 = int(cols.min()), int(cols.max()) + 1
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    out = []
    for i in range(n):
        a = int(round(x0 + (x1 - x0) * i / n)); b = int(round(x0 + (x1 - x0) * (i + 1) / n))
        out.append(card[y0:y1, a:b])
    return out


def main() -> int:
    pic = pathlib.Path(sys.argv[1])
    centres = None
    if "--centres" in sys.argv:
        centres = [tuple(int(v) for v in c.split(",")) for c in sys.argv[sys.argv.index("--centres") + 1].split(";")]
    import ddddocr
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    rec = ddddocr.DdddOcr(show_ad=False)
    card, box, src = prompt_card(img)
    field = img[:box[1], :]
    texts = [ocr(rec, card, s) for s in (2, 3, 4, 6)]
    chars = [c for c in max(texts, key=len) if is_cjk(c)]
    n = len(chars)
    cells = prompt_cells(card, n)
    p_maps = [norm_canvas(c) for c in cells]

    if centres:
        f_boxes = [(max(0, cx - 44), max(0, cy - 44), 88, 88) for (cx, cy) in centres]
        f_labels = [f"{cx},{cy}" for (cx, cy) in centres]
    else:
        from gt3_click_solve_dd import det_boxes
        det = ddddocr.DdddOcr(det=True, show_ad=False)
        fb = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
        mw = int(np.median([b[2] for b in fb])); mh = int(np.median([b[3] for b in fb]))
        f_boxes = []
        for (x, y, bw, bh) in fb:
            w, h = max(bw, mw), max(bh, mh)
            f_boxes.append((max(0, x - (w - bw) // 2), max(0, y - (h - bh) // 2), w, h))
        f_labels = [f"{x},{y}" for (x, y, _w, _h) in f_boxes]
    f_maps = [norm_canvas(field[y:y + h, x:x + w]) for (x, y, w, h) in f_boxes]

    print(f"card={src} text={json.dumps(texts, ensure_ascii=True)} n={n}")
    print("field:", f_labels)
    print("\ngradient NCC (higher better):")
    for i in range(n):
        row = [ncc(p_maps[i], f)[0] for f in f_maps]
        order = np.argsort(row)[::-1]
        second = row[order[1]] if len(order) > 1 else float('nan')
        print(f"  P{i} '{chars[i]}' " + "  ".join(f"{v:6.3f}" for v in row)
              + f"   best=F{order[0]} 2nd=F{order[1] if len(order) > 1 else -1} margin={row[order[0]] - second:.3f}")

    tiles = [(f"P{i}", p_maps[i]) for i in range(n)] + [(f"F{j}", f_maps[j]) for j in range(len(f_maps))]
    cw = OUT + 12
    canvas = np.zeros((OUT + 34, cw * len(tiles), 3), np.uint8)
    for k, (lab, t) in enumerate(tiles):
        x = k * cw + 6
        v = cv2.normalize(t, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        canvas[2:2 + OUT, x:x + OUT] = cv2.cvtColor(v, cv2.COLOR_GRAY2BGR)
        cv2.putText(canvas, lab, (x, OUT + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    out = TASK / "cache" / "eval_grad2.png"
    cv2.imencode(".png", canvas)[1].tofile(str(out))
    print("[montage]", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

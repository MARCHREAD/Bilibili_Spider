"""Stroke-vs-stroke matching test.

The card shows a filled black glyph; the field shows a thick neon outline.  Filled-vs-
outline comparisons fail, so the card glyph is reduced to its OUTLINE (morphological
gradient) and compared with the field glyph's k-means colour cluster, both as thin
strokes, using symmetric chamfer over a rotation/scale sweep.
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
SCALES = (0.85, 0.95, 1.05, 1.15, 1.3)


def card_cell_outlines(card: np.ndarray, n: int):
    g = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    m = (g < 140).astype(np.uint8) * 255
    m[:1, :] = 0; m[-1:, :] = 0; m[:, :1] = 0; m[:, -1:] = 0
    cols = np.where((m > 0).sum(axis=0) > 0)[0]
    rows = np.where((m > 0).sum(axis=1) > 0)[0]
    x0, x1 = int(cols.min()), int(cols.max()) + 1
    y0, y1 = int(rows.min()), int(rows.max()) + 1
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    out = []
    for i in range(n):
        a = int(round(x0 + (x1 - x0) * i / n)); b = int(round(x0 + (x1 - x0) * (i + 1) / n))
        cell = m[y0:y1, a:b]
        cell = cv2.morphologyEx(cell, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8))
        outline = cv2.morphologyEx(cell, cv2.MORPH_GRADIENT, se)
        if outline.sum() == 0:                     # degenerate: fall back to the fill
            outline = cell
        out.append(outline)
    return out


def kmeans_masks(crop: np.ndarray, k: int = 3) -> list[np.ndarray]:
    z = crop.reshape(-1, 3).astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, labels, _ = cv2.kmeans(z, k, None, crit, 4, cv2.KMEANS_PP_CENTERS)
    out = []
    for i in range(k):
        m = (labels.reshape(crop.shape[:2]) == i).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        n, lab, stats, _ = cv2.connectedComponentsWithStats(m, 8)
        keep = np.zeros_like(m)
        for j in range(1, n):
            if stats[j][4] >= 25:
                keep[lab == j] = 255
        out.append(keep)
    return out


def sym_chamfer(pm: np.ndarray, fm: np.ndarray) -> tuple[float, int, float]:
    """Mean over template ink of the distance to target ink, PLUS the same the other way.

    The forward term alone is degenerate (a thin template parked inside a solid blob
    scores 0), which is exactly what happened before; the backward term is evaluated at
    the offset the forward term chose.
    """
    base = norm_height(pm, H)
    target = (norm_height(fm, H) > 0).astype(np.uint8)
    if base.sum() < 15 or target.sum() < 15:
        return 1e9, 0, 1.0
    dt_t = cv2.distanceTransform(1 - target, cv2.DIST_L2, 3)
    ys, xs = np.where(target > 0)
    best, best_a, best_s = 1e9, 0, 1.0
    for a in ANG:
        rot = rotate_mask(base, a) if a else base
        for s in SCALES:
            tpl = cv2.resize(rot, None, fx=s, fy=s, interpolation=cv2.INTER_NEAREST) if s != 1.0 else rot
            th, tw = tpl.shape
            ink = float((tpl > 0).sum()) or 1.0
            if ink < 10:
                continue
            pad = np.full((dt_t.shape[0] + th, dt_t.shape[1] + tw), 1e3, np.float32)
            pad[:dt_t.shape[0], :dt_t.shape[1]] = dt_t
            resp = cv2.filter2D(pad, cv2.CV_32F, (tpl > 0).astype(np.float32), anchor=(0, 0),
                                borderType=cv2.BORDER_CONSTANT)
            oy, ox = np.unravel_index(int(np.argmin(resp)), resp.shape)
            fwd = float(resp[oy, ox]) / ink
            # backward: distance from every target ink pixel to the placed template
            placed = np.zeros((pad.shape[0] + th, pad.shape[1] + tw), np.uint8)
            placed[oy:oy + th, ox:ox + tw] = (tpl > 0).astype(np.uint8)
            dt_p = cv2.distanceTransform(1 - placed, cv2.DIST_L2, 3)
            bwd = float(dt_p[ys, xs].mean())
            v = 0.5 * (fwd + bwd)
            if v < best:
                best, best_a, best_s = v, a, s
    return best, best_a, best_s


def main() -> int:
    pic = pathlib.Path(sys.argv[1])
    cases = None
    if "--cases" in sys.argv:
        cases = json.loads(pathlib.Path(sys.argv[sys.argv.index("--cases") + 1]).read_text(encoding="utf-8"))
    import ddddocr
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    rec = ddddocr.DdddOcr(show_ad=False)
    card, box, src = prompt_card(img)
    field = img[:box[1], :]
    texts = [ocr(rec, card, s) for s in (2, 3, 4, 6)]
    chars = [c for c in max(texts, key=len) if is_cjk(c)]
    n = len(chars)
    p_out = card_cell_outlines(card, n)
    if cases is None:
        cases = [{"name": "g1", "cx": 195, "cy": 185}, {"name": "g2", "cx": 290, "cy": 63},
                 {"name": "g3", "cx": 280, "cy": 157}]
    glyphs = []
    for c in cases:
        half = 46
        crop = field[max(0, c["cy"] - half):c["cy"] + half, max(0, c["cx"] - half):c["cx"] + half]
        glyphs.append({"name": c["name"], "masks": kmeans_masks(crop, 3)})

    print(f"card={src} text={json.dumps(texts, ensure_ascii=True)} chars={json.dumps(chars, ensure_ascii=True)}")
    print("\nstroke chamfer (lower better), min over each glyph's colour clusters:")
    for i in range(n):
        row, detail = [], []
        for g in glyphs:
            best, bi, ba = 1e9, 0, 0
            for ci, m in enumerate(g["masks"]):
                v, a, _s = sym_chamfer(p_out[i], m)
                if v < best:
                    best, bi, ba = v, ci, a
            row.append(best); detail.append(f"{g['name']}#{bi}@{ba}")
        order = np.argsort(row)
        print(f"  P{i} '{chars[i]}' " + "  ".join(f"{v:6.2f}({d})" for v, d in zip(row, detail))
              + f"   best={glyphs[order[0]]['name']}")

    tiles = [("P%d" % i, norm_height(p_out[i], H)) for i in range(n)]
    for g in glyphs:
        for ci, m in enumerate(g["masks"]):
            tiles.append((f"{g['name']}#{ci}", norm_height(m, H)))
    cw = max(t[1].shape[1] for t in tiles) + 12
    canvas = np.zeros((H + 30, cw * len(tiles), 3), np.uint8)
    for k, (lab, t) in enumerate(tiles):
        x = k * cw + 6
        canvas[2:2 + t.shape[0], x:x + t.shape[1]] = cv2.cvtColor(t, cv2.COLOR_GRAY2BGR)
        cv2.putText(canvas, lab, (x, H + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    out = TASK / "cache" / "stroke_match.png"
    cv2.imencode(".png", canvas)[1].tofile(str(out))
    print("[montage]", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

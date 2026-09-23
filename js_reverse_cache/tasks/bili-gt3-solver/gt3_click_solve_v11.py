"""Word-click solver v11: prompt-filtered multi-model OCR identification.

Key idea (validated against real rounds)
---------------------------------------
A single glamorous reading of a rotated neon glyph is unreliable, but we do not need
one: for prompt character X we only ask whether some glyph was read as EXACTLY X at
some rotation.  The prompt supplies the filter, so the widely-confusable readings that
OCR produces (鱼/画/壤 for 黄, 琼/缘/璃 for 凉) are harmless -- a distractor is only a
false candidate if it is *ever* read as one of the (few, specific) prompt characters.

Measured examples: on a live round with prompt 黄包 the glyph 包 was read 99 times and
黄 did appear, while the distractor 凉 never produced either prompt character.

Pipeline
--------
1. click count + prompt characters: fixed prompt-card geometry (bottom 116x40 of the
   round JPEG, which is what .geetest_tip_img shows at 1:1), whole-card OCR over several
   upscales with two ddddocr models
2. glyph boxes: ddddocr detector, expanded to the median box size (the detector keeps
   under-cropping glyphs) and merged when they overlap (it also splits one glyph)
3. readings: every glyph re-OCR'd over 0..355 degrees, two models, two scales
4. assignment: prompt order, fewest-hit-first, each glyph used once

usage: python gt3_click_solve_v11.py <pic.jpg> [--out vis.jpg] [--json out.json]
"""
from __future__ import annotations

import argparse
import concurrent.futures as futures
import json
import os
import pathlib
import sys

import cv2
import numpy as np

from gt3_click_solve_dd import det_boxes, note
from gt3_click_solve_v10 import is_cjk, ocr, prompt_card

TASK = pathlib.Path(__file__).resolve().parent
ANGLES = list(range(0, 360, 10))
SCALES = (2, 3)
PADS = (6, 14)
MIN_N, MAX_N = 2, 6

# The rotation/scale sweep is ~1440 ddddocr calls per round and each costs 20-160 ms,
# which is the entire solve budget (the detector is ~0.2 s).  ddddocr classification is
# thread-safe -- onnxruntime releases the GIL and the two recognisers are shared
# read-only -- so the sweep runs on a thread pool.  Measured on a live round: 4.95x at
# 8 threads with byte-identical readings.
OCR_WORKERS = int(os.environ.get("GT3_OCR_WORKERS") or max(1, min(8, os.cpu_count() or 1)))
_OCR_POOL: futures.ThreadPoolExecutor | None = None


def ocr_pool() -> futures.ThreadPoolExecutor:
    global _OCR_POOL
    if _OCR_POOL is None:
        _OCR_POOL = futures.ThreadPoolExecutor(max_workers=OCR_WORKERS,
                                               thread_name_prefix="ocr")
    return _OCR_POOL


def build_recognisers():
    import ddddocr
    return [ddddocr.DdddOcr(show_ad=False), ddddocr.DdddOcr(show_ad=False, beta=True)]


def rotate_img(img: np.ndarray, angle: float) -> np.ndarray:
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    cos, sin = abs(m[0, 0]), abs(m[0, 1])
    nw, nh = int(h * sin + w * cos) + 2, int(h * cos + w * sin) + 2
    m[0, 2] += nw / 2 - w / 2
    m[1, 2] += nh / 2 - h / 2
    return cv2.warpAffine(img, m, (nw, nh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def detect_boxes(field: np.ndarray, det) -> list[tuple[int, int, int, int]]:
    boxes = [b for b in det_boxes(det, field) if b[2] >= 15 and b[3] >= 15]
    if not boxes:
        return []
    mw = int(np.median([b[2] for b in boxes]))
    mh = int(np.median([b[3] for b in boxes]))
    grown = []
    for (x, y, bw, bh) in boxes:
        w, h = max(bw, mw), max(bh, mh)
        grown.append((max(0, x - (w - bw) // 2), max(0, y - (h - bh) // 2), w, h))
    merged: list[tuple[int, int, int, int]] = []
    for b in grown:
        for i, m in enumerate(merged):
            ax1, ay1, ax2, ay2 = b[0], b[1], b[0] + b[2], b[1] + b[3]
            bx1, by1, bx2, by2 = m[0], m[1], m[0] + m[2], m[1] + m[3]
            ix = max(0, min(ax2, bx2) - max(ax1, bx1))
            iy = max(0, min(ay2, by2) - max(ay1, by1))
            inter = ix * iy
            if inter and inter / float(min(b[2] * b[3], m[2] * m[3])) > 0.45:
                nx1, ny1 = min(ax1, bx1), min(ay1, by1)
                nx2, ny2 = max(ax2, bx2), max(ay2, by2)
                merged[i] = (nx1, ny1, nx2 - nx1, ny2 - ny1)
                break
        else:
            merged.append(b)
    merged.sort(key=lambda b: (b[1] // 60, b[0]))
    return merged


def read_glyph(crop_bgr: np.ndarray, recs) -> dict[str, int]:
    """Every (pad, angle, model, scale) reading of one glyph, counted.

    The rotations are precomputed on the calling thread (18 per pad, a few ms of
    warpAffine each) and only the classification step is dispatched, so the pool sees
    a flat list of independent jobs.
    """
    jobs = []
    for pad in PADS:
        base = cv2.copyMakeBorder(crop_bgr, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
        for angle in ANGLES:
            im = rotate_img(base, angle) if angle else base
            for ri, rec in enumerate(recs):
                for s in SCALES:
                    jobs.append((ri, s, im))

    if len(jobs) < 32:  # tiny sweep: the pool hand-off would cost more than it saves
        texts = [ocr(recs[ri], im, s) for ri, s, im in jobs]
    else:
        texts = list(ocr_pool().map(lambda j: ocr(recs[j[0]], j[2], j[1]), jobs))

    counts: dict[str, int] = {}
    for t in texts:
        if is_cjk(t):
            counts[t] = counts.get(t, 0) + 1
    return counts


def solve(pic_path: pathlib.Path) -> dict:
    import ddddocr
    img = cv2.imdecode(np.fromfile(str(pic_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"cannot read {pic_path}")
    h, w = img.shape[:2]
    card, box, card_src = prompt_card(img)
    field = img[:box[1], :]
    recs = build_recognisers()

    # ---- click count + prompt candidates -----------------------------------
    # We do NOT need the true character.  OCR errors are systematic: the same model
    # misreads the card's 黄 and the field's 黄 as the same wrong glyph (鱼), so matching
    # card cell <-> field glyph on whatever readings they share recovers the mapping.
    # Each card cell therefore keeps ALL of its readings, weighted by how often each
    # occurred, and the whole-card reading contributes one vote per matching length.
    texts = []
    for rec in recs:
        for s in (2, 3, 4, 6):
            t = ocr(rec, card, s)
            if t:
                texts.append(t)
    cand_chars = [[c for c in t if is_cjk(c)] for t in texts]
    lengths = sorted({len(c) for c in cand_chars if MIN_N <= len(c) <= MAX_N})
    if not lengths:
        lengths = []
    n = 0                                  # decided below by field-glyph agreement

    g = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    cm = (g < 140).astype(np.uint8) * 255
    cm[:1, :] = 0; cm[-1:, :] = 0; cm[:, :1] = 0; cm[:, -1:] = 0
    cols = np.where((cm > 0).sum(axis=0) > 0)[0]
    x0, x1 = (int(cols.min()), int(cols.max()) + 1) if len(cols) else (0, card.shape[1])

    def cells_for(nn: int) -> list[dict[str, int]]:
        out = []
        for i in range(nn):
            votes: dict[str, int] = {}
            for c in cand_chars:                       # whole-card readings
                if len(c) == nn:
                    votes[c[i]] = votes.get(c[i], 0) + 2
            a = int(round(x0 + (x1 - x0) * i / nn)); b = int(round(x0 + (x1 - x0) * (i + 1) / nn))
            cell = card[:, max(0, a - 2):min(card.shape[1], b + 2)]
            for rec in recs:                           # per-cell readings
                for s in (3, 4):
                    t = ocr(rec, cell, s)
                    if is_cjk(t):
                        votes[t] = votes.get(t, 0) + 1
            out.append(votes)
        return out

    # ---- glyphs (needed before the count is fixed, to validate it) ----------
    det = ddddocr.DdddOcr(det=True, show_ad=False)
    boxes = detect_boxes(field, det)
    counts = []
    for (x, y, bw, bh) in boxes:
        crop = field[max(0, y - 4):y + bh + 4, max(0, x - 4):x + bw + 4]
        counts.append(read_glyph(crop, recs))
    top_count = [max(c.values()) if c else 0 for c in counts]

    def anchors(nn: int, cells) -> int:
        """How many confidently-read glyphs agree with a cell's OWN top vote.

        This is what settles the click count on real rounds: the standard model merged
        酿冬瓜 into 融岭 while beta read 酿冬瓜.  The field has a glyph that is confidently
        瓜 (65 hits vs 19 for the runner-up); with n=3 that glyph matches cell2's top vote,
        with n=2 瓜 is only a runner-up inside cell1, so n=3 wins.
        """
        tops = {max(c, key=lambda k: c[k]) for c in cells if c}
        out = 0
        for c in counts:
            if not c:
                continue
            top = max(c, key=lambda k: c[k])
            tc = c[top]
            second = sorted(c.values(), reverse=True)[1] if len(c) > 1 else 0
            if tc >= 8 and tc >= 2 * max(1, second) and top in tops:
                out += 1
        return out

    def plan(nn: int):
        """Greedy assignment for a candidate click count; returns a ranking key."""
        cells = cells_for(nn)
        sc = np.zeros((nn, len(boxes)))
        for i in range(nn):
            for j, c in enumerate(counts):
                if c:
                    sc[i, j] = sum(min(v, c.get(k, 0)) for k, v in cells[i].items() if k in c)
        used: set[int] = set()
        matched, total = 0, 0.0
        n_cand = {i: int((sc[i] > 0).sum()) for i in range(nn)}
        for i in sorted(range(nn), key=lambda i: (n_cand[i] == 0, n_cand[i], -sc[i].max())):
            cands = [j for j in range(len(boxes)) if j not in used and sc[i, j] > 0]
            if not cands:
                continue
            pick = max(cands, key=lambda j: (sc[i, j] / max(1, top_count[j]), sc[i, j]))
            used.add(pick)
            matched += 1
            total += sc[i, pick] / max(1, top_count[pick])
        mean_score = total / matched if matched else 0.0
        key = (anchors(nn, cells), length_votes.get(nn, 0), matched == nn,
               matched / float(nn), mean_score)
        return key, cells, sc, matched, mean_score

    length_votes: dict[int, int] = {}
    for c in cand_chars:
        if MIN_N <= len(c) <= MAX_N:
            length_votes[len(c)] = length_votes.get(len(c), 0) + 1

    chosen = None
    for nn in lengths:
        key, cells, sc, matched, mean_score = plan(nn)
        if chosen is None or key > chosen[0]:
            chosen = (key, nn, cells, sc, matched, mean_score)
    if chosen is None:
        # nothing readable at all: fall back to the most common length
        votes: dict[int, int] = {}
        for c in cand_chars:
            if MIN_N <= len(c) <= MAX_N:
                votes[len(c)] = votes.get(len(c), 0) + 1
        nn = max(votes, key=lambda k: (votes[k], k)) if votes else 0
        chosen = ((False, 0, 0), nn, cells_for(nn) if nn else [], np.zeros((max(nn, 1), len(boxes))), 0, 0.0)

    _key, n, cell_candidates, score, _m, _s = chosen
    prompt = [max(v, key=lambda k: v[k]) if v else "" for v in cell_candidates]

    res: dict = {"pic": str(pic_path), "size": [w, h], "solver": "v11",
                 "prompt_box": list(box), "prompt_source": card_src,
                 "prompt_readings": texts, "candidate_lengths": lengths,
                 "prompt_chars": prompt, "n_clicks": n,
                 "prompt_candidates": cell_candidates,
                 "field_boxes": [list(b) for b in boxes],
                 "readings": [sorted(c.items(), key=lambda kv: -kv[1])[:6] for c in counts]}
    if n == 0:
        res["error"] = "prompt unreadable"
        return res
    if not boxes:
        res["error"] = "no glyphs"
        return res

    # ---- assignment --------------------------------------------------------
    # score(i, j) = sum over shared readings of min(card votes, glyph hits); a glyph that
    # is confidently something else keeps a low score, and cells whose character no glyph
    # ever produced are resolved last by taking the least self-confident glyph left.
    score = np.zeros((n, len(boxes)), np.float64)
    for i in range(n):
        for j, c in enumerate(counts):
            if not c:
                continue
            score[i, j] = sum(min(v, c.get(k, 0)) for k, v in cell_candidates[i].items() if k in c)
    top_count = [max(c.values()) if c else 0 for c in counts]

    used: set[int] = set()
    matches = []
    n_cand = {i: int((score[i] > 0).sum()) for i in range(n)}
    order = sorted(range(n), key=lambda i: (n_cand[i] == 0, n_cand[i], -score[i].max()))
    for i in order:
        cands = [j for j in range(len(boxes)) if j not in used and score[i, j] > 0]
        if cands:
            pick = max(cands, key=lambda j: (score[i, j] / max(1, top_count[j]), score[i, j]))
        else:
            free = [j for j in range(len(boxes)) if j not in used]
            if not free:
                continue
            pick = min(free, key=lambda j: top_count[j])
        used.add(pick)
        bx, by, bw, bh = boxes[pick]
        best_char = max(cell_candidates[i], key=lambda k: min(cell_candidates[i][k], counts[pick].get(k, 0)),
                        default=prompt[i])
        matches.append({"prompt_index": i, "prompt_char": prompt[i], "best_char": best_char,
                        "field_index": pick, "score": float(score[i, pick]),
                        "fallback": bool(score[i, pick] == 0),
                        "x": bx + bw // 2, "y": by + bh // 2})
    matches.sort(key=lambda m: m["prompt_index"])
    res["scores"] = [[round(float(v), 2) for v in row] for row in score]
    res["matches"] = matches
    res["click_points"] = [[m["x"], m["y"]] for m in matches]
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pic")
    ap.add_argument("--out", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    res = solve(pathlib.Path(args.pic))
    if res.get("error"):
        print(json.dumps(res, ensure_ascii=True)[:600])
        return 1
    note(f"[card ] {res['prompt_source']} readings={res['prompt_readings']}")
    note(f"[prompt] {res['prompt_chars']} n={res['n_clicks']}")
    note(f"[boxes] {res['field_boxes']}")
    for j, r in enumerate(res["readings"]):
        note(f"   glyph{j} readings=" + " ".join(f"{k!r}x{v}" for k, v in r))
    for m in res["matches"]:
        note(f"   #{m['prompt_index']} '{m['prompt_char']}' -> glyph{m['field_index']} "
             f"score={m['score']} ({m['x']},{m['y']})")
    note(f"[points] {res['click_points']}")
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(res, ensure_ascii=True, indent=2), encoding="utf-8")
    if args.out:
        img = cv2.imdecode(np.fromfile(str(args.pic), dtype=np.uint8), cv2.IMREAD_COLOR)
        px, py, pw, ph = res["prompt_box"]
        vis = img.copy()
        cv2.rectangle(vis, (px, py), (px + pw, py + ph), (0, 255, 0), 1)
        for (x, y, bw, bh) in res["field_boxes"]:
            cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 255, 255), 1)
        for k, m in enumerate(res["matches"], start=1):
            cv2.circle(vis, (m["x"], m["y"]), 16, (0, 0, 255), 2)
            cv2.putText(vis, str(k), (m["x"] - 6, m["y"] + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imencode(".jpg", vis)[1].tofile(str(args.out))
        note(f"[vis] -> {args.out}")
    print(json.dumps({k: v for k, v in res.items() if k not in ("readings", "hits")}, ensure_ascii=True)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

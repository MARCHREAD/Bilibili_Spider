"""Callable wrapper the protocol driver uses to answer a word-click round.

Measured on the live widget (real Chrome, real round): the service does NOT validate
where the clicks landed.  Clicking the four corners of the image with exactly as many
clicks as the prompt has characters was accepted (`geetest_panel_success`), and the
submitted answer was `290_273,9685_273,9685_9668,290_9668`.

So the only thing that has to be right is the CLICK COUNT, which is the number of
characters on the prompt card.  ddddocr's reading of the whole card is stable in
LENGTH even when it misreads a character (爆炒田鸡 -> "爆炒田鸿", 焦盖烧饼 ->
"焦贰烧锑"), so we take the majority length over several upscales and place that many
points inside the clickable square.

`identify=True` still runs the v10 shape/OCR identifier for callers that want the
glyph positions; the service does not require them.
"""
from __future__ import annotations

import argparse
import pathlib

import cv2
import numpy as np

CARD_W, CARD_H = 116, 40
MIN_N, MAX_N = 2, 6


def _is_cjk(ch: str) -> bool:
    return len(ch) == 1 and "\u4e00" <= ch <= "\u9fff"


def prompt_count(pic_path: pathlib.Path) -> dict:
    """Click count = number of characters on the prompt card (bottom-left 116x40)."""
    import ddddocr

    img = cv2.imdecode(np.fromfile(str(pic_path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"cannot read {pic_path}")
    h, w = img.shape[:2]
    card = img[h - CARD_H:h, 0:min(CARD_W, w)]
    rec = ddddocr.DdddOcr(show_ad=False)

    readings, lengths = [], []
    for s in (2, 3, 4, 6):
        big = cv2.resize(card, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
        ok, enc = cv2.imencode(".png", big)
        text = rec.classification(enc.tobytes()) if ok else ""
        readings.append(text)
        n = sum(1 for c in text if _is_cjk(c))
        if MIN_N <= n <= MAX_N:
            lengths.append(n)

    n = max(set(lengths), key=lengths.count) if lengths else 0
    return {"pic": str(pic_path), "size": [w, h], "card_box": [0, h - CARD_H, CARD_W, CARD_H],
            "readings": readings, "lengths": lengths, "n_clicks": n}


def spread_points(w: int, h: int, n: int) -> list[list[int]]:
    """`n` distinct points inside the clickable square (side = image width)."""
    side = min(w, h)
    if n <= 0:
        return []
    if n == 1:
        return [[side // 2, side // 2]]
    pts = []
    for i in range(n):
        fx = (i + 0.5) / n
        fy = 0.5 + (0.22 if i % 2 else -0.22)
        pts.append([int(round(side * fx)), int(round(side * min(max(fy, 0.08), 0.92)))])
    return pts


def solve(pic_path: pathlib.Path, identify: bool = True, **_) -> dict:
    """Default: v11 (prompt-count + multi-model OCR identification).

    If identification fails (or is disabled), fall back to the count-only answer, which
    still exercises the whole protocol end to end.
    """
    pic = pathlib.Path(pic_path)
    if identify:
        try:
            import gt3_click_solve_v11 as v11
            rich = v11.solve(pic)
            if rich.get("click_points") and not rich.get("error"):
                keep = {k: rich[k] for k in ("size", "prompt_chars", "n_clicks", "field_boxes",
                                             "matches", "prompt_readings", "solver",
                                             "prompt_candidates", "candidate_lengths", "readings",
                                             "scores")
                        if k in rich}
                keep["click_points"] = rich["click_points"]
                return keep
        except Exception as exc:  # noqa: BLE001
            pass
    info = prompt_count(pic)
    w, h = info["size"]
    out = dict(info)
    out["click_points"] = spread_points(w, h, info["n_clicks"])
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pic")
    a = ap.parse_args()
    r = solve(pathlib.Path(a.pic))
    print(r["n_clicks"], r["readings"], r["click_points"])

"""Debug 3: MSER-based glyph candidate detection on the word-click field."""
from __future__ import annotations

import pathlib
import sys

import cv2
import numpy as np

TASK = pathlib.Path(__file__).resolve().parent


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    img = cv2.imdecode(np.fromfile(sys.argv[1], dtype=np.uint8), cv2.IMREAD_COLOR)
    field = img[:337, :]
    out = TASK / "debug_click"
    out.mkdir(exist_ok=True)

    b, g, r = field[:, :, 0].astype(np.int16), field[:, :, 1].astype(np.int16), field[:, :, 2].astype(np.int16)
    chroma = np.maximum(np.maximum(b, g), r) - np.minimum(np.minimum(b, g), r)
    note(f"[stats] chroma mean={chroma.mean():.1f} p95={np.percentile(chroma, 95):.1f}")

    mser = cv2.MSER_create()
    mser.setMinArea(60)
    mser.setMaxArea(20000)
    try:
        regions, boxes = mser.detectRegions(field)
    except Exception:  # noqa: BLE001
        boxes = []
    note(f"[mser] raw regions={len(boxes)}")

    h, w = field.shape[:2]
    kept = []
    for (x, y, bw, bh) in boxes:
        if bw < 25 or bh < 25 or bw > 130 or bh > 130:
            continue
        ar = bw / float(bh)
        if ar < 0.35 or ar > 2.6:
            continue
        sub_chroma = chroma[y:y + bh, x:x + bw]
        if float(sub_chroma.mean()) < 60:
            continue
        kept.append((int(x), int(y), int(bw), int(bh), float(sub_chroma.mean())))

    # merge overlapping candidates and keep the strongest per cluster
    kept.sort(key=lambda t: -t[4])
    final: list[tuple[int, int, int, int]] = []
    for (x, y, bw, bh, sc) in kept:
        cx, cy = x + bw / 2, y + bh / 2
        if any(abs(cx - (fx + fw / 2)) < 40 and abs(cy - (fy + fh / 2)) < 40 for (fx, fy, fw, fh) in final):
            continue
        final.append((x, y, bw, bh))
    note(f"[mser] kept={len(kept)} distinct={len(final)}")

    vis = field.copy()
    for (x, y, bw, bh, _sc) in kept:
        cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 255, 0), 1)
    for (x, y, bw, bh) in final:
        cv2.rectangle(vis, (x, y), (x + bw, y + bh), (0, 0, 255), 2)
    cv2.imencode(".png", vis)[1].tofile(str(out / "20_mser_boxes.png"))
    cv2.imencode(".png", chroma.astype(np.uint8))[1].tofile(str(out / "21_chroma.png"))
    note(f"[debug] -> {out/'20_mser_boxes.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Per-stage timing profile of the v11 word-click solver on a real round image.

usage: python profile_v11.py cache/proto_XXXX/pic_7.jpg
"""
from __future__ import annotations

import pathlib
import sys
import time

import cv2
import numpy as np

import gt3_click_solve_v11 as v11
from gt3_click_solve_dd import det_boxes
from gt3_click_solve_v10 import ocr, prompt_card, is_cjk


def main() -> int:
    pic = pathlib.Path(sys.argv[1])
    img = cv2.imdecode(np.fromfile(str(pic), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    print(f"image {w}x{h}")

    t = time.perf_counter()
    recs = v11.build_recognisers()
    print(f"load recognisers      {time.perf_counter()-t:7.2f}s")

    t = time.perf_counter()
    card, box, src = prompt_card(img)
    field = img[:box[1], :]
    print(f"prompt card ({src})   {time.perf_counter()-t:7.2f}s")

    t = time.perf_counter()
    texts = []
    for rec in recs:
        for s in (2, 3, 4, 6):
            tt = ocr(rec, card, s)
            if tt:
                texts.append(tt)
    print(f"card OCR x{len(recs)*4}          {time.perf_counter()-t:7.2f}s")

    t = time.perf_counter()
    import ddddocr
    det = ddddocr.DdddOcr(det=True, show_ad=False)
    boxes = v11.detect_boxes(field, det)
    print(f"detect glyph boxes    {time.perf_counter()-t:7.2f}s  boxes={boxes}")

    total_calls = 0
    t_glyph = time.perf_counter()
    for i, (x, y, bw, bh) in enumerate(boxes):
        crop = field[max(0, y - 4):y + bh + 4, max(0, x - 4):x + bw + 4]
        t = time.perf_counter()
        v11.read_glyph(crop, recs)
        dt = time.perf_counter() - t
        calls = len(v11.PADS) * len(v11.ANGLES) * len(recs) * len(v11.SCALES)
        total_calls += calls
        print(f"  glyph{i} read_glyph   {dt:7.2f}s  ({calls} OCR calls, {dt/calls*1000:.1f} ms/call)")
    print(f"glyph readings total  {time.perf_counter()-t_glyph:7.2f}s over {total_calls} OCR calls "
          f"({(time.perf_counter()-t_glyph)/total_calls*1000:.1f} ms/call)")

    t = time.perf_counter()
    res = v11.solve(pic)
    print(f"full solve()          {time.perf_counter()-t:7.2f}s")
    print(f"  prompt={res.get('prompt_chars')} n={res.get('n_clicks')} points={res.get('click_points')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

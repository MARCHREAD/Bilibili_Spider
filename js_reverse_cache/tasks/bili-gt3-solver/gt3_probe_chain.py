"""GT3 chain probe: reproduce the real geetest GT3 transcript in pure Python.

Phase A goal: capture every round artifact (challenge, c/s, images, gct path)
and learn exactly where the server rejects an empty `w`, so the later Node-VM
`w` helpers target the real failure surface instead of a guessed one.

GET only. No account state. Saves one self-contained round under cache/round_<ts>/.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np
from curl_cffi import requests

TASK = Path(__file__).resolve().parent
CACHE = TASK / "cache"
CACHE.mkdir(parents=True, exist_ok=True)

IMPERSONATE = "chrome146"
BILLI_CAPTCHA = "https://passport.bilibili.com/x/passport-login/captcha?source=main-fe"

# classic GT3 52-piece scramble map
SLICE_POSITIONS = [
    39, 38, 48, 49, 41, 40, 46, 47, 35, 34, 50, 51, 33, 32, 28, 29, 27, 26,
    36, 37, 31, 30, 44, 45, 43, 42, 12, 13, 23, 22, 14, 15, 21, 20, 8, 9,
    25, 24, 6, 7, 3, 2, 0, 1, 11, 10, 4, 5, 19, 18, 16, 17,
]

ROUND: dict = {}


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def jsonp(text: str) -> dict | None:
    m = re.search(r"\(\s*(\{.*\})\s*\)\s*;?\s*$", text.strip(), re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description="pure-python GT3 chain probe")
    ap.add_argument("--gt", default=None, help="override gt (default: live bilibili captcha init)")
    ap.add_argument("--challenge", default=None, help="override base challenge")
    ap.add_argument("--api", default="api.geetest.com", help="api server host")
    ap.add_argument("--out", default=None, help="round output dir")
    args = ap.parse_args()

    stamp = time.strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.out) if args.out else (CACHE / f"round_{stamp}")
    outdir.mkdir(parents=True, exist_ok=True)
    ROUND["outdir"] = str(outdir)

    s = requests.Session(impersonate=IMPERSONATE)
    s.headers.update({"Accept-Language": "zh-CN,zh;q=0.9", "Referer": "https://passport.bilibili.com/login"})
    api = args.api

    def get(url: str, name: str) -> tuple[int, str]:
        time.sleep(0.6)
        r = s.get(url, timeout=30)
        body = r.text
        (outdir / name).write_text(body, encoding="utf-8", errors="replace")
        with (TASK / "network.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"probe": name, "url": url, "status": r.status_code, "len": len(body)}) + "\n")
        note(f"[{name}] {r.status_code} {len(body)}B")
        return r.status_code, body

    # ---- 0. gt + base challenge ------------------------------------------
    if args.gt and args.challenge:
        gt, base = args.gt, args.challenge
        ROUND["gt_source"] = "cli-override"
    else:
        _, body = get(BILLI_CAPTCHA, "00_bili_captcha.json")
        data = json.loads(body)["data"]
        gt = data["geetest"]["gt"]
        base = data["geetest"]["challenge"]
        ROUND["bili_token"] = data["token"]
        ROUND["gt_source"] = "bilibili-live"
    ROUND["gt"] = gt
    ROUND["base_challenge"] = base
    note(f"[0] gt={gt} base_challenge={base}")

    # ---- 1. gettype ------------------------------------------------------
    _, body = get(f"https://{api}/gettype.php?gt={gt}&callback=geetest_{int(time.time()*1000)}", "01_gettype.txt")
    ROUND["gettype"] = jsonp(body)

    # ---- 2. initial get.php (no w: documented compatibility path) ---------
    _, body = get(
        f"https://{api}/get.php?gt={gt}&challenge={base}&lang=zh-cn&pt=0&client_type=web"
        f"&callback=geetest_{int(time.time()*1000)}",
        "02_get_initial.txt",
    )
    init = jsonp(body)
    ROUND["get_initial"] = init
    if init and init.get("data"):
        d = init["data"]
        ROUND["initial_keys"] = sorted(d.keys())
        ROUND["initial_c"] = d.get("c")
        ROUND["initial_s"] = d.get("s")
        note(f"[2] initial keys={sorted(d.keys())}")

    # ---- 3. pre-radar ajax.php (no w) ------------------------------------
    pre_url = (
        f"https://{api}/ajax.php?gt={gt}&challenge={base}&lang=zh-cn&pt=0&client_type=web"
        f"&w=&callback=geetest_{int(time.time()*1000)}"
    )
    _, body = get(pre_url, "03_ajax_pre.txt")
    ROUND["ajax_pre"] = jsonp(body)
    note(f"[3] pre={json.dumps(ROUND['ajax_pre'], ensure_ascii=False)[:200]}")

    # ---- 4. slide round: get.php?is_next=true ----------------------------
    _, body = get(
        f"https://{api}/get.php?is_next=true&type=slide3&gt={gt}&challenge={base}&lang=zh-cn&pt=0"
        f"&client_type=web&callback=geetest_{int(time.time()*1000)}",
        "04_get_slide.txt",
    )
    slide = jsonp(body)
    ROUND["get_slide"] = slide
    sd = (slide or {}).get("data") or {}
    ROUND["slide_keys"] = sorted(sd.keys())
    ROUND["slide_challenge"] = sd.get("challenge")
    ROUND["slide_c"] = sd.get("c")
    ROUND["slide_s"] = sd.get("s")
    ROUND["slide_ypos"] = sd.get("ypos")
    ROUND["gct_path"] = sd.get("gct_path")
    note(f"[4] slide keys={sorted(sd.keys())} challenge={sd.get('challenge')}")

    # ---- 5. images -------------------------------------------------------
    static = "https://static.geetest.com"
    imgs: dict[str, str] = {}
    for key in ("bg", "fullbg", "slice"):
        path = sd.get(key)
        if not path:
            continue
        url = path if path.startswith("http") else static + path
        time.sleep(0.4)
        r = s.get(url, timeout=30)
        if r.status_code == 200:
            fname = f"{key}{Path(path).suffix or '.jpg'}"
            (outdir / fname).write_bytes(r.content)
            imgs[key] = fname
            note(f"[5] {key} {len(r.content)}B -> {fname}")
    ROUND["images"] = imgs

    # ---- 6. restore + distance ------------------------------------------
    if "bg" in imgs and "fullbg" in imgs:
        def restore(path: Path) -> np.ndarray:
            src = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
            h, w = src.shape[:2]
            dst = np.zeros_like(src)
            for i, pos in enumerate(SLICE_POSITIONS):
                x, y = (i % 26) * 10, (i // 26) * 80
                sx, sy = (pos % 26) * 10, (pos // 26) * 80
                if sy + 80 <= h and sx + 10 <= w:
                    dst[y:y + 80, x:x + 10] = src[sy:sy + 80, sx:sx + 10]
            return dst

        bg = restore(outdir / imgs["bg"])
        full = restore(outdir / imgs["fullbg"])
        cv2.imwrite(str(outdir / "restored_bg.png"), bg)
        cv2.imwrite(str(outdir / "restored_fullbg.png"), full)

        diff = cv2.absdiff(bg, full)
        gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 25, 255, cv2.THRESH_BINARY)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = [cv2.boundingRect(c) for c in contours]
        boxes.sort(key=lambda b: b[2] * b[3], reverse=True)
        ROUND["diff_boxes"] = boxes[:5]
        if boxes:
            x, y, bw, bh = boxes[0]
            ROUND["gap_x"] = x
            ROUND["gap_box"] = [int(x), int(y), int(bw), int(bh)]
            ROUND["distance_minus6"] = int(x) - 6
            note(f"[6] gap box={x},{y},{bw},{bh} -> distance(candidate)=x-6={x-6}")

        if "slice" in imgs:
            piece = cv2.imdecode(np.fromfile(str(outdir / imgs["slice"]), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            ROUND["slice_shape"] = list(piece.shape)
            tmpl = piece[:, :, :3] if piece.ndim == 3 and piece.shape[2] == 4 else piece
            if tmpl.shape[0] <= full.shape[0] and tmpl.shape[1] <= full.shape[1]:
                res = cv2.matchTemplate(full, tmpl, cv2.TM_CCOEFF_NORMED)
                _, maxv, _, maxloc = cv2.minMaxLoc(res)
                ROUND["template_match"] = {"x": int(maxloc[0]), "y": int(maxloc[1]), "score": round(float(maxv), 4)}
                note(f"[6] template match x={maxloc[0]} y={maxloc[1]} score={maxv:.4f}")

    # ---- 7. final ajax.php with EMPTY w = negative control ---------------
    chal = ROUND.get("slide_challenge") or base
    _, body = get(
        f"https://{api}/ajax.php?gt={gt}&challenge={chal}&lang=zh-cn&$_BCm=0&client_type=web"
        f"&w=&callback=geetest_{int(time.time()*1000)}",
        "05_ajax_final_empty_w.txt",
    )
    ROUND["ajax_final_empty_w"] = jsonp(body)
    note(f"[7] final(empty w)={json.dumps(ROUND['ajax_final_empty_w'], ensure_ascii=False)[:300]}")

    (outdir / "round.json").write_text(json.dumps(ROUND, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in ROUND.items() if k not in ("get_slide", "gettype")}, ensure_ascii=True)[:2500])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

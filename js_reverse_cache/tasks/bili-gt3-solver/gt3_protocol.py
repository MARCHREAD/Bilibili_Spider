"""GT3 pure-protocol driver: Python owns every HTTP byte, the Node helper only
runs the raw geetest SDK and hands back the `w` it produces.

Protocol with env/run.js is JSON-lines over stdin/stdout.

usage: python gt3_protocol.py [--rounds 1] [--max-http 40] [--source main-fe]
"""
from __future__ import annotations

import argparse
import json
import pathlib

import cv2
import numpy as np
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

from curl_cffi import requests

TASK = Path(__file__).resolve().parent
CACHE = TASK / "cache"
HELPER = TASK / "env" / "run.js"
IMPERSONATE = "chrome146"
PATCHED_CORE = False
PATCHED_CLICK = False


T0 = time.perf_counter()


def note(msg: str) -> None:
    stamp = f"[t+{time.perf_counter() - T0:6.2f}s] "
    line = stamp + msg
    print(line.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


class Session:
    def __init__(self) -> None:
        self.s = requests.Session(impersonate=IMPERSONATE)
        self.s.headers.update({"Accept-Language": "zh-CN,zh;q=0.9", "Referer": "https://passport.bilibili.com/login"})
        self.used = 0
        self.log: list[dict] = []

    def get(self, url: str) -> tuple[int, str, str]:
        time.sleep(0.5)
        r = self.s.get(url, timeout=30)
        self.used += 1
        self.log.append({"url": url.split("?")[0], "status": r.status_code, "len": len(r.text)})
        note(f"[http {self.used}] {r.status_code} {len(r.text):>7}B  {url.split('?')[0]}")
        return r.status_code, r.text, r.headers.get("content-type", "")


def bili_captcha(sess: Session, source: str) -> tuple[str, str, str]:
    _, body, _ = sess.get(f"https://passport.bilibili.com/x/passport-login/captcha?source={source}")
    data = json.loads(body)["data"]
    return data["geetest"]["gt"], data["geetest"]["challenge"], data["token"]


def local_asset(url: str) -> str | None:
    name = url.split("?")[0].rsplit("/", 1)[-1]
    # the core-export patched copy stands in for the raw product asset when asked
    if name == "fullpage.9.2.0-guwyxh.js" and PATCHED_CORE:
        p = CACHE / "fullpage.patched-core.js"
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace")
    if name == "click.3.1.2.js" and PATCHED_CLICK:
        p = CACHE / "click.patched-widget.js"
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace")
    p = CACHE / name
    if p.exists():
        return p.read_text(encoding="utf-8", errors="replace")
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--max-http", type=int, default=40)
    ap.add_argument("--source", default="main-fe")
    ap.add_argument("--out", default=None)
    ap.add_argument("--probe-pre-ajax", action="store_true")
    ap.add_argument("--patched-core", action="store_true", help="serve the core-export patched product asset")
    ap.add_argument("--patched-click", action="store_true", help="serve the widget-export patched click asset")
    ap.add_argument("--probe-core", default=None, help="comma list of core methods to call once the flow stalls")
    ap.add_argument("--probe-all-core", action="store_true", help="call every core method once, watching for new requests")
    ap.add_argument("--synth-clicks", default=None, help="semicolon list of x,y points to dispatch as pointer events")
    ap.add_argument("--timer-cap", type=int, default=None, help="virtual-clock ms budget per timer drain")
    ap.add_argument("--synth-moves", default=None, help="count of synthetic mousemove samples for the behaviour tracker")
    ap.add_argument("--verify-first", action="store_true", help="call inst.verify() from the driver before dispatching clicks")
    ap.add_argument("--probe-args", default=None, help="argument shape for the sweep: object, array, string or numbers")
    ap.add_argument("--probe-target", default=None, help="sweep target: inst or core")
    ap.add_argument("--dump-inst", action="store_true", help="dump the product instance structure")
    ap.add_argument("--dump-values", action="store_true", help="dump own-property values of inst and core")
    ap.add_argument("--call-await", default=None, help="comma list of instance methods to call and await")
    ap.add_argument("--find-method", default=None, help="search the object graph for this method name")
    ap.add_argument("--call-widget", default=None, help="call this method on the captured widget object")
    ap.add_argument("--dump-widget", action="store_true", help="dump the captured widget and its answer tracker")
    ap.add_argument("--answer-format", default=None, help="answer encoding for the click submission")
    ap.add_argument("--answer-formats", default=None, help="comma list of answer encodings to try in one round")
    ap.add_argument("--helper-rounds", type=int, default=None, help="helper driving-loop round cap")
    ap.add_argument("--gt", default=None, help="pre-issued gt (skip the passport captcha prefetch)")
    ap.add_argument("--challenge", default=None, help="pre-issued challenge (must pair with --gt)")
    ap.add_argument("--token", default=None, help="pre-issued passport token (recorded for the caller)")
    ap.add_argument("--cookies", default=None, help="extra Cookie header for the geetest calls")
    ap.add_argument("--deadline", type=float, default=180.0,
                    help="wall-clock budget in seconds for the whole helper loop")
    args = ap.parse_args()

    global PATCHED_CORE, PATCHED_CLICK
    PATCHED_CORE = args.patched_core
    PATCHED_CLICK = args.patched_click

    sess = Session()
    if args.cookies:
        sess.s.headers["Cookie"] = args.cookies
    if args.gt and args.challenge:
        # The caller (biliwb) already prefetched the challenge with the session that
        # will submit the login. Reuse it verbatim: passport binds the token to the
        # prefetching session, so solving a *different* round's challenge cannot be
        # accepted by the login endpoint.
        gt, challenge, token = args.gt, args.challenge, (args.token or "")
        note(f"[prefetched] gt={gt} challenge={challenge} token={token} (no passport call)")
    else:
        gt, challenge, token = bili_captcha(sess, args.source)
    note(f"[round] gt={gt} challenge={challenge} token={token}")

    stamp = time.strftime("%Y%m%d-%H%M%S")
    outdir = Path(args.out) if args.out else (CACHE / f"proto_{stamp}")
    outdir.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        ["node", str(HELPER), "--gt", gt, "--challenge", challenge,
         "--assets", "loader", "--driver", "loader", "--dump-core"]
        + (["--probe-core", args.probe_core] if args.probe_core else [])
        + (["--probe-all-core"] if args.probe_all_core else [])
        + (["--max-rounds", str(args.helper_rounds)] if args.helper_rounds else [])
        + (["--synth-clicks", args.synth_clicks] if args.synth_clicks else [])
        + (["--timer-cap", str(args.timer_cap)] if args.timer_cap else [])
        + (["--synth-moves", args.synth_moves] if args.synth_moves else [])
        + (["--verify-first"] if args.verify_first else [])
        + (["--probe-args", args.probe_args] if args.probe_args else [])
        + (["--probe-target", args.probe_target] if args.probe_target else [])
        + (["--dump-inst"] if args.dump_inst else [])
        + (["--dump-values"] if args.dump_values else [])
        + (["--call-await", args.call_await] if args.call_await else [])
        + (["--find-method", args.find_method] if args.find_method else [])
        + (["--call-widget", args.call_widget] if args.call_widget else [])
        + (["--dump-widget"] if args.dump_widget else [])
        + (["--answer-formats", args.answer_formats] if args.answer_formats else []),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )

    result: dict = {"gt": gt, "base_challenge": challenge, "token": token, "requests": [], "http": sess.log}
    transcripts: list[dict] = []
    w_values: list[dict] = []

    def send(obj: dict) -> None:
        assert proc.stdin
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    deadline = time.time() + max(15.0, float(args.deadline))
    solved = False
    while True:
        if time.time() > deadline:
            note("[warn] helper timeout")
            break
        assert proc.stdout
        line = proc.stdout.readline()
        if not line:
            break
        try:
            msg = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        kind = msg.get("type")

        if kind == "ready":
            note(f"[helper] ready assets={msg.get('assets')} load={msg.get('loadLog')} diag={msg.get('diag')}")
            result["helper_ready"] = msg
            continue

        if kind in ("error", "fatal"):
            note(f"[helper:{kind}] {json.dumps(msg, ensure_ascii=True)[:200]}")
            result.setdefault("helper_errors", []).append(msg)
            continue

        if kind == "request":
            url = msg["url"]
            params = msg.get("params") or {}
            entry = {"id": msg["id"], "kind": msg.get("kind"), "path": url.split("?")[0], "params": params}
            # helper truncates long params for display, so take long values from
            # the raw URL query where they are still complete (and percent-encoded)
            raw_query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query, keep_blank_values=True)
            for key in ("w", "$_BCm"):
                values = raw_query.get(key)
                if values and values[0]:
                    w_values.append({
                        "id": msg["id"], "key": key, "value": values[0],
                        "path": url.split("?")[0], "url": url,
                        "encoded_in_url": urllib.parse.quote(values[0], safe="") in url,
                    })
            result["requests"].append(entry)
            w_len = len(raw_query.get("w", [""])[0])
            note(f"[helper:req {msg['id']}] {msg.get('kind')} {url.split('?')[0]} params={sorted(params)} w_len={w_len}")

            if sess.used >= args.max_http:
                send({"type": "response", "id": msg["id"], "kind": "json", "body": {"status": "error", "data": {}}})
                continue

            # data:/blob: URIs are feature probes; real images must load for the
            # click product to accept clicks, so answer with their true size
            if not url.startswith("http"):
                send({"type": "response", "id": msg["id"], "kind": "noop"})
                continue
            if msg.get("kind") == "img":
                try:
                    ir = sess.s.get(url, timeout=30)
                    sess.used += 1
                    sess.log.append({"url": url.split("?")[0], "status": ir.status_code, "len": len(ir.content)})
                    arr = np.frombuffer(ir.content, dtype=np.uint8)
                    decoded = cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)
                    ih, iw = (decoded.shape[0], decoded.shape[1]) if decoded is not None else (0, 0)
                    ext = pathlib.Path(url.split("?")[0]).suffix or ".jpg"
                    img_path = outdir / f"reqlmg_{msg['id']}{ext}"
                    img_path.write_bytes(ir.content)
                    note(f"[http {sess.used}] {ir.status_code} {len(ir.content):>7}B  IMG {iw}x{ih} -> {img_path.name}")
                    send({"type": "response", "id": msg["id"], "kind": "img", "width": int(iw), "height": int(ih)})
                except Exception as exc:  # noqa: BLE001
                    note(f"[warn] img fetch failed: {exc}")
                    send({"type": "response", "id": msg["id"], "kind": "noop"})
                continue

            path = url.split("?")[0]
            if path.endswith(".css") or msg.get("kind") == "link":
                # fetch for the record, then let the helper fire the load event
                if url.startswith("http") and sess.used < args.max_http:
                    try:
                        status, text, _ = sess.get(url)
                        (outdir / f"style_{msg['id']}.css").write_text(text, encoding="utf-8", errors="replace")
                    except Exception as exc:  # noqa: BLE001
                        note(f"[warn] css fetch failed: {exc}")
                send({"type": "response", "id": msg["id"], "kind": "link"})
                continue
            if path.endswith(".js") and "callback=" not in url:
                src = local_asset(url)
                if src is not None:
                    note(f"           -> served local asset {path.rsplit('/',1)[-1]} ({len(src)}B)")
                    send({"type": "response", "id": msg["id"], "kind": "js", "body": src})
                    continue
                status, text, ct = sess.get(url)
                send({"type": "response", "id": msg["id"], "kind": "js", "body": text})
                continue

            status, text, ct = sess.get(url)
            transcripts.append({"id": msg["id"], "url": url, "status": status, "body": text[:4000]})
            payload = None
            try:
                body = text[text.index("(") + 1 : text.rindex(")")]
                payload = json.loads(body)
            except Exception:  # noqa: BLE001
                payload = {"raw": text[:2000], "status": "unparsed"}
            # pull challenge images so the round can be inspected offline
            data = payload.get("data") if isinstance(payload, dict) else None
            if "/ajax.php" in path:
                note(f"[verdict] {path} -> {json.dumps(payload, ensure_ascii=True)[:300]}")
                verdict = (data or {}).get("result") if isinstance(data, dict) else None
                if verdict == "success":
                    result["validate"] = data.get("validate")
                    result["score"] = data.get("score")
                    note(f"=== SUCCESS validate={data.get('validate')} score={data.get('score')} ===")
                    solved = True
            for scope_name, scope in (("top", payload), ("data", data)):
                if isinstance(scope, dict) and any(
                    k in scope for k in ("pic_type", "spec", "num", "sign", "gct")
                ):
                    keep = {k: scope.get(k) for k in
                            ("status", "result", "num", "pic_type", "spec", "sign", "type", "c", "gct")}
                    note(f"[round {scope_name}] {json.dumps(keep, ensure_ascii=True)[:320]}")
            if isinstance(data, dict):
                servers = data.get("image_servers") or data.get("static_servers") or ["static.geetest.com/"]
                for key in ("pic", "bg", "fullbg", "slice"):
                    rel = data.get(key)
                    if not isinstance(rel, str) or not rel:
                        continue
                    if rel.startswith("http"):
                        img_url = rel
                    else:
                        img_url = "https://" + servers[0].rstrip("/") + (rel if rel.startswith("/") else "/" + rel)
                    if sess.used >= args.max_http:
                        break
                    time.sleep(0.4)
                    ir = sess.s.get(img_url, timeout=30)
                    sess.used += 1
                    sess.log.append({"url": img_url.split("?")[0], "status": ir.status_code, "len": len(ir.content)})
                    ext = pathlib.Path(rel).suffix or ".jpg"
                    img_path = outdir / f"{key}_{msg['id']}{ext}"
                    img_path.write_bytes(ir.content)
                    note(f"[http {sess.used}] {ir.status_code} {len(ir.content):>7}B  IMAGE {key} -> {img_path.name}")
                    result.setdefault("images", []).append({"id": msg["id"], "key": key, "file": img_path.name, "bytes": len(ir.content), "url": img_url})
            send({"type": "response", "id": msg["id"], "kind": "json", "body": payload})
            if solved:
                # the challenge is consumed once validate is returned; further submits
                # only earn error_51/error_12 and waste requests
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
                break
            continue

        if kind == "done":
            note(f"[helper] done requests={len(msg.get('requests') or [])} log={msg.get('log')} errors={msg.get('errors')}")
            result["helper_done"] = msg
            break

        if kind == "need-points":
            pts, fmt = "", "raw"
            wanted = args.answer_format or "raw"
            sol = None
            raw_points: list = []
            pics = [im for im in (result.get("images") or []) if im.get("key") == "pic"]
            if pics:
                img_path = outdir / pics[-1]["file"]
                try:
                    import gt3_click_api as solver
                    _st = time.perf_counter()
                    sol = solver.solve(img_path)
                    solve_ms = int((time.perf_counter() - _st) * 1000)
                    pts = sol.get("click_points") or []
                    raw_points = list(pts)
                    note(f"[solver] {img_path.name} -> points={pts} ranked={sol.get('ranked')}")
                    # machine-readable summary for the local test UI (app/server.py)
                    note("[solve] " + json.dumps({
                        "pic": img_path.name,
                        # absolute path: round images are named pic_7.jpg every round, so
                        # the name alone cannot be mapped back to a cache dir afterwards
                        "pic_path": str(img_path),
                        "solver": sol.get("solver"),
                        "solve_ms": solve_ms,
                        "prompt": sol.get("prompt_chars"),
                        "candidates": sol.get("prompt_candidates"),
                        "readings": sol.get("prompt_readings"),
                        "n": sol.get("n_clicks"),
                        "points": raw_points,
                        "field_boxes": sol.get("field_boxes"),
                        "matches": sol.get("matches"),
                        "size": sol.get("size"),
                    }, ensure_ascii=True))
                except Exception as exc:  # noqa: BLE001
                    note(f"[warn] solver failed: {exc}")
            if wanted in ("pct", "str") and pts and sol:
                # word/phrase click answer as the product builds it (class Le.$_FAA):
                # each marker stores round(100 * percent), joined "x_y,x_y".
                # Measured against the real widget: the click area is the square
                # .geetest_item_wrap (side = display width) with the round image drawn
                # background-size:100% auto from its top-left, so a natural pixel
                # (px,py) sits at (px,py) * wrapW/imgW from the wrap origin and
                #   x = round(10000*px/imgW),  y = round(10000*py/imgW)
                # i.e. BOTH axes divide by the image WIDTH; the bottom 384-344 rows are
                # the prompt card and are clipped out of the click area entirely.
                w, h = sol.get("size") or (0, 0)
                if w and h:
                    pts = ",".join(
                        f"{round(10000.0 * p[0] / w)}_{round(10000.0 * p[1] / w)}" for p in pts
                    )
                    fmt = "str"
                    note(f"[answer] pct={pts} (img {w}x{h}, click square={w})")
                else:
                    note("[warn] solver returned no image size; falling back to raw")
            elif wanted not in ("raw", "pct", "str"):
                fmt = wanted
            send({"type": "points", "points": pts, "format": fmt})
            continue

        # anything else (core-dump, decode, ...) is kept verbatim
        result.setdefault("helper_other", []).append(msg)
        limit = 2600 if kind in ("call-widget", "core-dump", "probe") else 400
        note(f"[helper:{kind}] {json.dumps(msg, ensure_ascii=True)[:limit]}")
        continue

    try:
        proc.stdin.close()  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.wait(timeout=15)
    except Exception:  # noqa: BLE001
        proc.kill()

    result["transcripts"] = transcripts
    result["w_values"] = w_values
    result["http_used"] = sess.used

    # --- follow-up: is the SDK-produced initial w also the pre-radar w? ----
    if args.probe_pre_ajax and w_values:
        last = w_values[-1]
        raw_q = urllib.parse.urlparse(last["url"]).query
        raw_w = urllib.parse.parse_qs(raw_q, keep_blank_values=True).get(last["key"], [""])[0]
        reencoded = urllib.parse.quote(last["value"], safe="")
        note(f"=== follow-up: {last['key']} len={len(last['value'])} reencode_matches_url={reencoded == raw_w} ===")
        result["w_encoding_check"] = {
            "decoded_len": len(last["value"]),
            "url_len": len(raw_w),
            "reencode_matches": reencoded == raw_w,
        }

        def ajax(body_params: dict) -> dict:
            url = "https://api.geetest.com/ajax.php?" + urllib.parse.urlencode(body_params)
            status, text, _ = sess.get(url)
            try:
                return {"status": status, "body": json.loads(text[text.index("(") + 1 : text.rindex(")")])}
            except Exception:  # noqa: BLE001
                return {"status": status, "body": {"raw": text[:400]}}

        cb = f"geetest_{int(time.time()*1000)}"
        pre = ajax({
            "gt": gt, "challenge": challenge, "lang": "zh-cn", "pt": "0",
            "client_type": "web", "w": last["value"], "callback": cb,
        })
        result["pre_ajax_with_initial_w"] = pre
        note(f"--- pre-radar with initial w (properly encoded) -> {json.dumps(pre['body'], ensure_ascii=True)[:300]}")

        slide_params = {
            "is_next": "true", "type": "slide3", "gt": gt, "challenge": challenge,
            "lang": "zh-cn", "pt": "0", "client_type": "web", "w": last["value"],
            "callback": f"geetest_{int(time.time()*1000)}",
        }
        url = "https://api.geetest.com/get.php?" + urllib.parse.urlencode(slide_params)
        status, text, _ = sess.get(url)
        try:
            slide = json.loads(text[text.index("(") + 1 : text.rindex(")")])
        except Exception:  # noqa: BLE001
            slide = {"raw": text[:400]}
        result["slide_get_with_initial_w"] = {"status": status, "body": slide}
        keys = sorted((slide.get("data") or {}).keys()) if isinstance(slide, dict) else []
        note(f"--- slide get.php with initial w -> keys={keys}")

    (outdir / "protocol.json").write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    (outdir / "w_values.json").write_text(json.dumps(w_values, ensure_ascii=True, indent=2), encoding="utf-8")

    note("=== w values captured ===")
    for w in w_values:
        note(f"  id={w['id']} key={w['key']} path={w['path']} len={len(w['value'])} head={w['value'][:40]}")
    note(f"=== http used: {sess.used} ===")
    print(json.dumps({
        "gt": gt, "challenge": challenge,
        "requests": [{"kind": r["kind"], "path": r["path"], "params": sorted(r["params"])} for r in result["requests"]],
        "w_lengths": [len(w["value"]) for w in w_values],
        "http_used": sess.used,
        "outdir": str(outdir),
    }, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

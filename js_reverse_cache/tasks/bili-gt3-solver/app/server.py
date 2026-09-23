"""Local debug server for the browser-free GT3 solver.

    python app/server.py            # http://127.0.0.1:8795

Endpoints
---------
GET  /                                  the test UI (app/ui/index.html)
POST /api/run        {"rounds": 1|2|3}  start a background solve run -> {"run_id": "..."}
GET  /api/run/<id>?log_from=N           status + parsed summary + new log lines
POST /api/run/<id>/stop                 kill the running child
GET  /api/runs                          history (newest first)
GET  /api/image/<id>/<file>             a saved round image from that run
GET  /api/health                        {"ok": true, "task": ...}

Each run executes gt3_protocol.py exactly as main.py does (fresh challenge from
passport.bilibili.com, node VM runs the raw geetest assets, v11 solves the word-click
round, the widget's own $_BJJQ builds the final `w`).  Nothing about the run path
touches a browser.
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TASK = pathlib.Path(__file__).resolve().parent.parent
UI = pathlib.Path(__file__).resolve().parent / "ui"
SERVER = pathlib.Path(__file__).resolve().parent / "server.py"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8795

RUNS: dict[str, dict] = {}
LOCK = threading.Lock()

RE_VERDICT = re.compile(r"\[verdict\]\s+\S+\s+->\s+(\{.*\})\s*$")
RE_SUCCESS = re.compile(r"=== SUCCESS validate=(\S+) score=(\S+) ===")
RE_SOLVE = re.compile(r"\[solve\]\s+(\{.*\})\s*$")
RE_ANSWER = re.compile(r"\[answer\]\s+pct=(\S+)")
RE_IMAGE = re.compile(r"IMAGE pic -> (\S+\.(?:jpg|jpeg|png))")
RE_ROUND = re.compile(r"\[round\]\s+gt=(\S+)\s+challenge=(\S+)")
RE_HTTP = re.compile(r"http used:\s*(\d+)")
RE_WLEN = re.compile(r"=== w values captured ===")
RE_WLINE = re.compile(r"id=(\d+)\s+key=(\w+)\s+path=(\S+)\s+len=(\d+)")


def parse_line(run: dict, line: str) -> None:
    line = line.rstrip("\n")
    if not line:
        return
    m = RE_ROUND.search(line)
    if m:
        run["gt"], run["challenge"] = m.group(1), m.group(2)
    m = RE_SOLVE.search(line)
    if m:
        try:
            info = json.loads(m.group(1))
            run["solve"] = info
            run["pic"] = info.get("pic") or run.get("pic")
            run["prompt"] = info.get("prompt")
            run["points"] = info.get("points")
            run["n_clicks"] = info.get("n")
        except Exception:  # noqa: BLE001
            pass
    m = RE_IMAGE.search(line)
    if m:
        run["pic"] = m.group(1)
    m = RE_ANSWER.search(line)
    if m:
        run["wire_answer"] = m.group(1)
    m = RE_WLINE.search(line)
    if m:
        run.setdefault("w_values", []).append(
            {"id": int(m.group(1)), "key": m.group(2), "path": m.group(3), "len": int(m.group(4))}
        )
    m = RE_VERDICT.search(line)
    if m:
        try:
            verdict = json.loads(m.group(1))
        except Exception:  # noqa: BLE001
            verdict = {"raw": m.group(1)}
        run["verdict"] = verdict
        data = verdict.get("data") if isinstance(verdict, dict) else None
        if isinstance(data, dict) and data.get("result") == "success":
            run["validate"] = data.get("validate")
            run["score"] = data.get("score")
            run["ok"] = True
    m = RE_SUCCESS.search(line)
    if m:
        run["validate"], run["score"], run["ok"] = m.group(1), m.group(2), True
    m = RE_HTTP.search(line)
    if m:
        run["http_used"] = int(m.group(1))


def runner(run_id: str, rounds: int, max_http: int) -> None:
    run = RUNS[run_id]
    cmd = [sys.executable, str(TASK / "gt3_protocol.py"),
           "--max-http", str(max_http), "--patched-core", "--patched-click",
           "--call-widget", "$_BJJQ", "--answer-format", "pct", "--verify-first",
           "--timer-cap", "2000", "--helper-rounds", "80"]
    for i in range(1, rounds + 1):
        if run.get("cancelled"):
            break
        run["round_index"] = i
        run["push"](f"===== round {i}/{rounds} =====")
        try:
            proc = subprocess.Popen(cmd, cwd=str(TASK), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, bufsize=1)
        except Exception as exc:  # noqa: BLE001
            run["push"](f"[api] cannot start driver: {exc}")
            break
        run["proc"] = proc
        assert proc.stdout
        for line in proc.stdout:
            run["push"](line.rstrip("\n"))
            parse_line(run, line)
        proc.wait()
        run["proc"] = None
        if run.get("ok"):
            run["push"](f"[api] round {i} solved: validate={run.get('validate')} score={run.get('score')}")
        else:
            run["push"](f"[api] round {i} did not return a validate code")
        run["results"].append({"round": i, "ok": bool(run.get("ok")),
                               "validate": run.get("validate"), "score": run.get("score"),
                               "prompt": run.get("prompt"), "pic": run.get("pic")})
        # a fresh run for the next round
        run["ok"] = run["ok"] if i < rounds else run["ok"]
        run["validate"] = run.get("validate") if i < rounds else run.get("validate")
    run["status"] = "done"
    run["finished"] = time.time()
    run["push"]("[api] run finished")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    def handle_one_request(self):
        """Browsers drop keep-alive sockets constantly; that is not an error."""
        try:
            super().handle_one_request()
        except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            self.close_connection = True

    # -- helpers -----------------------------------------------------------
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: pathlib.Path, ctype: str):
        if not path.exists() or not path.is_file():
            self.send_json({"error": "not found", "path": str(path)}, 404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    # -- routes ------------------------------------------------------------
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        query = {}
        if "?" in self.path:
            for kv in self.path.split("?", 1)[1].split("&"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    query[k] = v

        if path in ("/", "/index.html"):
            self.send_file(UI / "index.html", "text/html; charset=utf-8")
            return
        if path == "/api/health":
            self.send_json({"ok": True, "task": str(TASK), "runs": len(RUNS)})
            return
        if path == "/api/runs":
            with LOCK:
                items = [{"id": rid, "status": r.get("status"), "started": r.get("started"),
                          "rounds": r.get("rounds"), "ok": r.get("ok"),
                          "validate": r.get("validate"), "score": r.get("score"),
                          "prompt": r.get("prompt"), "challenge": r.get("challenge"),
                          "results": r.get("results")}
                         for rid, r in RUNS.items()]
            items.sort(key=lambda x: x.get("started") or 0, reverse=True)
            self.send_json({"runs": items[:30]})
            return
        if path.startswith("/api/run/"):
            run_id = path[len("/api/run/"):].split("/")[0]
            run = RUNS.get(run_id)
            if not run:
                self.send_json({"error": "unknown run"}, 404)
                return
            log_from = int(query.get("log_from", "0") or 0)
            with LOCK:
                log = run["log"]
                new = log[log_from:]
                payload = {
                    "id": run_id, "status": run.get("status"), "started": run.get("started"),
                    "rounds": run.get("rounds"), "round_index": run.get("round_index"),
                    "gt": run.get("gt"), "challenge": run.get("challenge"),
                    "prompt": run.get("prompt"), "points": run.get("points"),
                    "n_clicks": run.get("n_clicks"), "pic": run.get("pic"),
                    "wire_answer": run.get("wire_answer"), "verdict": run.get("verdict"),
                    "validate": run.get("validate"), "score": run.get("score"), "ok": run.get("ok"),
                    "http_used": run.get("http_used"), "w_values": run.get("w_values"),
                    "solve": run.get("solve"), "results": run.get("results"),
                    "log_total": len(log), "log": new,
                }
            self.send_json(payload)
            return
        if path.startswith("/api/image/"):
            rest = path[len("/api/image/"):]
            parts = rest.split("/", 1)
            if len(parts) != 2:
                self.send_json({"error": "bad image path"}, 400)
                return
            run_id, name = parts
            run = RUNS.get(run_id)
            if not run or not run.get("outdir"):
                self.send_json({"error": "unknown run"}, 404)
                return
            safe = pathlib.Path(name).name
            ctype = "image/jpeg" if safe.lower().endswith((".jpg", ".jpeg")) else "image/png"
            self.send_file(pathlib.Path(run["outdir"]) / safe, ctype)
            return
        self.send_json({"error": "not found", "path": path}, 404)

    def do_POST(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/run":
            body = self.read_body()
            rounds = max(1, min(5, int(body.get("rounds") or 1)))
            max_http = max(8, min(60, int(body.get("max_http") or 20)))
            run_id = uuid.uuid4().hex[:10]
            log: list[str] = []

            def push(line: str):
                with LOCK:
                    log.append(line)
                    if len(log) > 4000:
                        del log[:1000]

            RUNS[run_id] = {"id": run_id, "status": "running", "started": time.time(),
                            "rounds": rounds, "log": log, "push": push, "results": [],
                            "outdir": None, "ok": False, "cancelled": False, "proc": None}
            threading.Thread(target=runner, args=(run_id, rounds, max_http), daemon=True).start()
            self.send_json({"run_id": run_id, "rounds": rounds})
            return
        if path.startswith("/api/run/") and path.endswith("/stop"):
            run_id = path[len("/api/run/"):-len("/stop")]
            run = RUNS.get(run_id)
            if not run:
                self.send_json({"error": "unknown run"}, 404)
                return
            run["cancelled"] = True
            proc = run.get("proc")
            if proc:
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            run["status"] = "stopped"
            run["push"]("[api] stop requested")
            self.send_json({"stopped": run_id})
            return
        self.send_json({"error": "not found", "path": path}, 404)


def outdir_watch() -> None:
    """Attach each run's newest cache/proto_* directory so images can be served."""
    while True:
        time.sleep(1.0)
        with LOCK:
            runs = list(RUNS.values())
        for run in runs:
            if run.get("outdir") or run.get("status") != "running":
                continue
            cands = sorted(TASK.glob("cache/proto_*"), key=lambda p: p.stat().st_mtime)
            for c in reversed(cands):
                if c.stat().st_mtime >= (run.get("started") or 0) - 1:
                    run["outdir"] = str(c)
                    break


if __name__ == "__main__":
    threading.Thread(target=outdir_watch, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"GT3 debug UI on http://127.0.0.1:{PORT}/  (task={TASK})", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass

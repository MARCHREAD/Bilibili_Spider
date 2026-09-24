"""本地工作台 HTTP 服务（FastAPI）+ 静态 UI。

多账号 / 多 worker
------------------
* `AccountPool` 管理 N 个账号，每个账号一个独立 `BiliClient`（独立 cookie 与限速）。
* `JobRunner` 用 N 个 worker 线程跑任务；job 绑定账号，账号级锁保证同账号串行。
* 采集始终发生在本进程的 Python 里；页面只是本地控制面板，不参与目标请求。
"""

from __future__ import annotations

import csv
import io
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from curl_cffi import requests as cffi
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, Response

from . import __version__
from . import constants as C
from .accounts import AccountPool
from .client import BiliClient
from .errors import BiliError
from .jobs import KIND_LABEL, KINDS, JobRunner
from .store import MidHashIndex, Store

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"

OUR_BUGS = (ImportError, NameError, AttributeError, TypeError)
DEFAULT_WORKERS = 3
MAX_WORKERS = 32


def _flatten_csv(value: Any, prefix: str = "", out: dict | None = None) -> dict:
    out = out if out is not None else {}
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            _flatten_csv(item, path, out)
    elif isinstance(value, list):
        out[prefix or "value"] = json.dumps(value, ensure_ascii=False, default=str)
    else:
        out[prefix or "value"] = value
    return out


def _csv_safe(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _results_csv(results: list[dict]) -> str:
    rows: list[dict] = []
    fields: list[str] = ["target", "ok", "error", "duration_ms"]
    for result in results:
        payload = result.get("payload")
        items = payload.get("items") if isinstance(payload, dict) else None
        values = items if isinstance(items, list) else [payload]
        if not values:
            values = [None]
        for value in values:
            row = {
                "target": result.get("target"),
                "ok": bool(result.get("ok")),
                "error": result.get("error"),
                "duration_ms": result.get("duration_ms"),
            }
            if isinstance(value, dict):
                _flatten_csv(value, out=row)
            elif value is not None:
                row["value"] = value
            for key in row:
                if key not in fields:
                    fields.append(key)
            rows.append(row)

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _csv_safe(row.get(key)) for key in fields})
    return "\ufeff" + stream.getvalue()


def create_app(data_dir: str | Path = "data", workers: int = DEFAULT_WORKERS) -> FastAPI:
    data = Path(data_dir)
    data.mkdir(parents=True, exist_ok=True)

    store = Store(data / "biliwb.db")
    index = MidHashIndex(store)
    pool = AccountPool(store, data_dir=data, midhash_index=index)

    # 兼容旧的单会话：把 data/session.txt 迁成「默认」账号
    legacy = data / "session.txt"
    if not store.list_accounts() and legacy.exists():
        raw = legacy.read_text(encoding="utf-8").strip()
        if raw:
            try:
                pool.create("默认", login_method="cookie", cookie=raw)
                print("[biliwb] 已把 data/session.txt 迁移为账号「默认」", file=sys.stderr)
            except ValueError as exc:
                print(f"[biliwb] 迁移旧会话失败: {exc}", file=sys.stderr)

    runner = JobRunner(pool, store, workers=max(1, min(int(workers), MAX_WORKERS)))
    app = FastAPI(title="bilibili 本地采集工作台", version=__version__)

    # ------------------------------------------------------------ 工具

    def guard(fn, trace_client: BiliClient | None = None):
        """统一错误出口：我方 bug 响亮报警，外部错误结构化返回。"""
        started = time.perf_counter()
        trace: list[dict] | None = None
        if trace_client is not None:
            trace_client.begin_trace()

        def meta() -> dict:
            nonlocal trace
            if trace is None:
                trace = trace_client.end_trace() if trace_client is not None else []
            return {
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                "http_calls": len(trace),
                "trace": trace,
            }

        try:
            return {"ok": True, "data": fn(), "meta": meta()}
        except HTTPException:
            raise
        except OUR_BUGS as exc:
            print(f"!!! 我方代码缺陷: {type(exc).__name__}: {exc}", file=sys.stderr)
            traceback.print_exc()
            return JSONResponse({"ok": False, "error": f"我方代码缺陷: {exc}",
                                 "kind": "internal", "meta": meta()}, status_code=500)
        except BiliError as exc:
            print(f"[api] {type(exc).__name__}: {exc}", file=sys.stderr)
            return JSONResponse({"ok": False, "error": str(exc),
                                 "code": exc.code, "kind": type(exc).__name__,
                                 "meta": meta()})
        except Exception as exc:  # noqa: BLE001
            print(f"[api] {type(exc).__name__}: {exc}", file=sys.stderr)
            return JSONResponse({"ok": False, "error": f"{type(exc).__name__}: {exc}",
                                 "kind": "external", "meta": meta()})

    def account_or_400(account_id: int | None) -> int:
        aid = account_id if account_id else pool.pick()
        if aid is None:
            raise HTTPException(400, "没有可用账号：请先在「账号」页添加并校验")
        if not store.get_account(aid):
            raise HTTPException(404, f"账号不存在: {aid}")
        return int(aid)

    # ------------------------------------------------------------ 静态

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB / "index.html")

    @app.get("/app.js")
    def app_js() -> FileResponse:
        return FileResponse(WEB / "app.js", media_type="application/javascript")

    @app.get("/style.css")
    def style_css() -> FileResponse:
        return FileResponse(WEB / "style.css", media_type="text/css")

    @app.get("/api/image")
    def image_proxy(url: str) -> Response:
        """为搜索卡片转发 B 站图片，补齐 Referer 并限制可访问域名。"""
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        allowed = host == "bilibili.com" or host.endswith((".bilibili.com", ".hdslb.com"))
        if parsed.scheme != "https" or not allowed:
            raise HTTPException(400, "仅支持 bilibili/hdslb 的 HTTPS 图片")
        try:
            response = cffi.get(
                url,
                headers={"Referer": C.WWW + "/"},
                impersonate=C.IMPERSONATE,
                timeout=15,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"图片请求失败: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise HTTPException(502, f"图片上游返回 HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
        if not content_type.startswith("image/"):
            raise HTTPException(502, "图片上游返回了非图片内容")
        return Response(
            content=response.content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=3600"},
        )

    # ------------------------------------------------------------ 总览

    @app.get("/api/status")
    def status() -> Any:
        accounts = pool.list_public()
        return {
            "ok": True,
            "data": {
                "version": __version__,
                "accounts": accounts,
                "account_count": len(accounts),
                "healthy_count": len(pool.healthy_ids()),
                "workers": runner.workers_status(),
                "store": store.stats(),
                "default_account_id": pool.pick(),
                "kinds": [{"kind": k, "label": KIND_LABEL[k]} for k in KINDS],
                "search_orders": C.SEARCH_ORDERS,
                "search_durations": {str(k): v for k, v in C.SEARCH_DURATIONS.items()},
                "security": pool.describe_security(),
            },
        }

    @app.get("/api/workers")
    def workers_get() -> Any:
        return {"ok": True, "data": runner.workers_status()}

    @app.post("/api/workers")
    def workers_set(payload: dict) -> Any:
        def run():
            want = int(payload.get("workers", runner.workers))
            if not 1 <= want <= MAX_WORKERS:
                raise HTTPException(400, f"workers 需在 1..{MAX_WORKERS}")
            runner.set_workers(want)
            return runner.workers_status()
        return guard(run)

    # ------------------------------------------------------------ 账号

    @app.get("/api/accounts")
    def accounts_list() -> Any:
        return {"ok": True, "data": pool.list_public()}

    @app.post("/api/accounts")
    def account_create(payload: dict) -> Any:
        return guard(lambda: pool.create(
            str(payload.get("alias") or "").strip(),
            login_method=str(payload.get("login_method") or "qr"),
            username=payload.get("username") or None,
            password=payload.get("password") or None,
            cookie=payload.get("cookie") or None,
        ))

    @app.delete("/api/accounts/{account_id}")
    def account_delete(account_id: int) -> Any:
        return guard(lambda: {"deleted": pool.delete(account_id)})

    @app.post("/api/accounts/{account_id}/credentials")
    def account_credentials(account_id: int, payload: dict) -> Any:
        return guard(lambda: pool.set_credentials(
            account_id,
            username=payload.get("username"),
            password=payload.get("password"),
            cookie=payload.get("cookie"),
        ))

    @app.post("/api/accounts/{account_id}/verify")
    def account_verify(account_id: int) -> Any:
        return guard(lambda: pool.verify(account_id))

    @app.post("/api/accounts/verify-all")
    def accounts_verify_all(payload: dict | None = None) -> Any:
        return guard(lambda: pool.verify_all(workers=runner.workers))

    @app.post("/api/accounts/{account_id}/login/qr")
    def account_qr(account_id: int) -> Any:
        return guard(lambda: pool.qr_start(account_id))

    @app.get("/api/accounts/{account_id}/login/qr/poll")
    def account_qr_poll(account_id: int, qrcode_key: str) -> Any:
        return guard(lambda: pool.qr_poll(account_id, qrcode_key))

    @app.post("/api/accounts/{account_id}/login/password")
    def account_password(account_id: int, payload: dict | None = None) -> Any:
        payload = payload or {}
        # 每轮验证码都要重跑一次极验（约 13~17s）；上限 3 轮，避免无意义地刷风控
        attempts = max(1, min(int(payload.get("attempts") or 2), 3))
        return guard(lambda: pool.login_password(
            account_id, source=str(payload.get("source") or "main-fe"),
            attempts=attempts))

    @app.post("/api/accounts/{account_id}/cookie")
    def account_cookie(account_id: int, payload: dict) -> Any:
        return guard(lambda: pool.import_cookie(account_id, str(payload.get("cookie") or "")))

    # ---------------------------------------------- status=2 短信二次验证（半自动）
    # 密码登录返回 status=2 时，服务端要求短信校验绑定手机号。这两步只自动化
    # "过人机验证码 / 发短信 / 换 cookie"，短信内容本身只有用户能看到。

    @app.get("/api/accounts/{account_id}/risk/status")
    def account_risk_status(account_id: int) -> Any:
        return guard(lambda: pool.risk_status(account_id))

    @app.post("/api/accounts/{account_id}/risk/sms/send")
    def account_risk_sms_send(account_id: int) -> Any:
        return guard(lambda: pool.risk_send_sms(account_id))

    @app.post("/api/accounts/{account_id}/risk/sms/verify")
    def account_risk_sms_verify(account_id: int, payload: dict) -> Any:
        return guard(lambda: pool.risk_verify_sms(
            account_id, str((payload or {}).get("code") or "")))

    @app.get("/api/accounts/security")
    def accounts_security() -> Any:
        return {"ok": True, "data": pool.describe_security()}

    # ------------------------------------------------------------ 单次调用 / 批量

    @app.post("/api/call")
    def call(payload: dict) -> Any:
        kind = payload.get("kind")
        if kind not in KINDS:
            raise HTTPException(400, f"未知能力: {kind}")
        target = str(payload.get("target") or "").strip()
        if not target:
            raise HTTPException(400, "target 不能为空")
        options = payload.get("options") or {}
        account_id = account_or_400(payload.get("account_id"))
        client = pool.client(account_id)
        api = pool.api(account_id)

        def run():
            with pool.lock(account_id):
                return KINDS[kind](api, target, options)

        return guard(run, trace_client=client)

    @app.post("/api/jobs")
    def create_job(payload: dict) -> Any:
        kind = payload.get("kind")
        if kind not in KINDS:
            raise HTTPException(400, f"未知能力: {kind}")
        targets = payload.get("targets") or []
        if isinstance(targets, str):
            targets = list(targets.replace(",", "\n").split("\n"))
        shard = bool(payload.get("shard"))
        account_id = payload.get("account_id")
        if account_id in ("", None) and not shard:
            account_id = pool.pick()
        return guard(lambda: {"job_id": runner.submit(
            kind, targets, payload.get("options") or {},
            account_id=int(account_id) if account_id not in ("", None) else None,
            shard=shard)})

    @app.get("/api/jobs")
    def list_jobs(limit: int = 30) -> Any:
        return {"ok": True, "data": store.list_jobs(limit)}

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: int, with_results: bool = True) -> Any:
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        if with_results:
            job["results"] = store.list_results(job_id)
        if job.get("account_id"):
            acc = store.get_account(job["account_id"]) or {}
            job["account_alias"] = acc.get("alias")
        return {"ok": True, "data": job}

    @app.get("/api/jobs/{job_id}/export.csv")
    def job_export_csv(job_id: int) -> Response:
        job = store.get_job(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        content = _results_csv(store.list_results(job_id, limit=100000))
        filename = f"biliwb-job-{job_id}-{job['kind']}.csv"
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: int) -> Any:
        runner.cancel(job_id)
        return {"ok": True, "data": {"cancelled": job_id}}

    @app.get("/api/records")
    def list_records(kind: str | None = None, limit: int = 50) -> Any:
        return {"ok": True, "data": store.list_records(kind, limit)}

    @app.get("/api/records/{record_id}")
    def record_detail(record_id: int) -> Any:
        item = store.get_record(record_id)
        if not item:
            raise HTTPException(404, "记录不存在")
        return {"ok": True, "data": item}

    @app.get("/api/midhash-index")
    def midhash_index(limit: int = 50) -> Any:
        return {"ok": True, "data": {"stats": store.stats(),
                                     "top": store.midhash_top(limit)}}

    return app

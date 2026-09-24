"""SQLite 存储：任务、结果、采集记录。

单文件库，默认放在项目 data/biliwb.db；批量任务可断点续跑（已成功的 target 跳过）。
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    targets     TEXT NOT NULL,
    options     TEXT NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'pending',
    total       INTEGER NOT NULL DEFAULT 0,
    done        INTEGER NOT NULL DEFAULT 0,
    failed      INTEGER NOT NULL DEFAULT 0,
    error       TEXT,
    account_id  INTEGER,
    shard       INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL,
    finished_at INTEGER
);
CREATE TABLE IF NOT EXISTS job_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL,
    target      TEXT NOT NULL,
    ok          INTEGER NOT NULL,
    payload     TEXT,
    error       TEXT,
    duration_ms REAL,
    trace       TEXT,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_job_results_job ON job_results(job_id);
CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    key         TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_kind ON records(kind, created_at DESC);

-- midHash -> uid 持久字典。
-- midHash 只是 uid 的函数（crc32），与视频无关，所以一旦通过任何途径确认了
-- 一对 (midHash, uid)，就可以在**所有**视频里复用，命中率随时间累积上升。
CREATE TABLE IF NOT EXISTS midhash_index (
    mid_hash   TEXT PRIMARY KEY,
    uid        INTEGER NOT NULL,
    uname      TEXT,
    level      INTEGER,
    source     TEXT,
    hits       INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_midhash_uid ON midhash_index(uid);

-- 多账号：cookie 与密码一律加密存储（见 biliwb/secrets.py），不落明文。
CREATE TABLE IF NOT EXISTS accounts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    alias            TEXT NOT NULL UNIQUE,
    mid              INTEGER,
    uname            TEXT,
    face             TEXT,
    login_method     TEXT NOT NULL DEFAULT 'qr',   -- qr | password | cookie
    username         TEXT,                          -- 密码登录用的账号名
    password_enc     BLOB,                          -- 加密后的密码
    cookie_enc       BLOB,                          -- 加密后的 cookie 串
    enabled          INTEGER NOT NULL DEFAULT 1,
    last_status      TEXT,
    last_error       TEXT,
    last_verified_at INTEGER,
    created_at       INTEGER NOT NULL,
    updated_at       INTEGER NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path = "data/biliwb.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        """给已存在的旧库补列（CREATE TABLE IF NOT EXISTS 不会改结构）。"""
        cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(jobs)")}
        for name, ddl in (("account_id", "ALTER TABLE jobs ADD COLUMN account_id INTEGER"),
                          ("shard", "ALTER TABLE jobs ADD COLUMN shard INTEGER DEFAULT 0")):
            if name not in cols:
                self._conn.execute(ddl)
        result_cols = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(job_results)")
        }
        for name, ddl in (
            ("duration_ms", "ALTER TABLE job_results ADD COLUMN duration_ms REAL"),
            ("trace", "ALTER TABLE job_results ADD COLUMN trace TEXT"),
        ):
            if name not in result_cols:
                self._conn.execute(ddl)

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------ 任务

    def create_job(self, kind: str, targets: list[str], options: dict,
                   account_id: int | None = None, shard: bool = False) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO jobs(kind, targets, options, status, total,"
                " account_id, shard, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (kind, json.dumps(targets, ensure_ascii=False),
                 json.dumps(options, ensure_ascii=False), "pending",
                 len(targets), account_id, 1 if shard else 0, int(time.time())),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def update_job(self, job_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {cols} WHERE id=?",
                               (*fields.values(), job_id))
            self._conn.commit()

    def mark_stale_jobs_interrupted(self) -> int:
        """把上个进程遗留的 running/pending 任务标记为 interrupted。

        进程重启后这些任务**不可能**还在执行（worker 线程随进程消失），但库里仍写着
        running —— 界面会一直显示一个永不结束的"运行中"僵尸任务（实测残留过 job 21）。
        """
        with self._lock:
            cur = self._conn.execute(
                "UPDATE jobs SET status='interrupted', finished_at=?,"
                " error=COALESCE(error, '进程重启，任务已中断')"
                " WHERE status IN ('running','pending')",
                (int(time.time()),))
            self._conn.commit()
            return int(cur.rowcount)

    def get_job(self, job_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._job_row(row) if row else None

    def list_jobs(self, limit: int = 30) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [self._job_row(r) for r in rows]

    @staticmethod
    def _job_row(row: sqlite3.Row) -> dict:
        job = dict(row)
        job["targets"] = json.loads(job["targets"])
        job["options"] = json.loads(job["options"])
        return job

    def add_result(self, job_id: int, target: str, ok: bool,
                   payload: Any = None, error: str | None = None,
                   duration_ms: float | None = None,
                   trace: list[dict] | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO job_results(job_id,target,ok,payload,error,duration_ms,trace,created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (job_id, target, 1 if ok else 0,
                 json.dumps(payload, ensure_ascii=False, default=str) if payload is not None else None,
                 error, duration_ms,
                 json.dumps(trace, ensure_ascii=False, default=str) if trace is not None else None,
                 int(time.time())),
            )
            self._conn.commit()

    def list_results(self, job_id: int, limit: int = 200) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM job_results WHERE job_id=? ORDER BY id LIMIT ?",
            (job_id, limit)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            if item.get("payload"):
                try:
                    item["payload"] = json.loads(item["payload"])
                except Exception:
                    pass
            if item.get("trace"):
                try:
                    item["trace"] = json.loads(item["trace"])
                except Exception:
                    item["trace"] = []
            else:
                item["trace"] = []
            out.append(item)
        return out

    def completed_targets(self, job_id: int) -> set[str]:
        rows = self._conn.execute(
            "SELECT target FROM job_results WHERE job_id=? AND ok=1", (job_id,)).fetchall()
        return {r["target"] for r in rows}

    def find_resumable(self, kind: str, options: dict) -> dict | None:
        """找同 kind+options 的未完成任务，用于"续跑"。"""
        rows = self._conn.execute(
            "SELECT * FROM jobs WHERE kind=? AND status IN ('pending','running','paused')"
            " ORDER BY id DESC LIMIT 5", (kind,)).fetchall()
        for row in rows:
            job = self._job_row(row)
            if job["options"] == options:
                return job
        return None

    # ------------------------------------------------------------ 采集记录

    def save_record(self, kind: str, key: str, payload: Any) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO records(kind,key,payload,created_at) VALUES (?,?,?,?)",
                (kind, key, json.dumps(payload, ensure_ascii=False, default=str),
                 int(time.time())),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def list_records(self, kind: str | None = None, limit: int = 50) -> list[dict]:
        if kind:
            rows = self._conn.execute(
                "SELECT * FROM records WHERE kind=? ORDER BY id DESC LIMIT ?",
                (kind, limit)).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM records ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def get_record(self, record_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM records WHERE id=?", (record_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        try:
            item["payload"] = json.loads(item["payload"])
        except Exception:
            pass
        return item

    def stats(self) -> dict:
        jobs = self._conn.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
        recs = self._conn.execute("SELECT COUNT(*) c FROM records").fetchone()["c"]
        idx = self._conn.execute("SELECT COUNT(*) c FROM midhash_index").fetchone()["c"]
        return {"jobs": jobs, "records": recs, "midhash_index": idx, "db": str(self.path)}

    # ------------------------------------------------------------ midHash 字典

    def midhash_lookup(self, hashes: set[str] | list[str]) -> dict[str, dict]:
        """批量查 midHash -> {uid, uname, level}。"""
        items = [h for h in set(hashes) if h]
        if not items:
            return {}
        out: dict[str, dict] = {}
        CHUNK = 400
        for start in range(0, len(items), CHUNK):
            chunk = items[start:start + CHUNK]
            marks = ",".join("?" * len(chunk))
            rows = self._conn.execute(
                f"SELECT mid_hash, uid, uname, level FROM midhash_index WHERE mid_hash IN ({marks})",
                chunk).fetchall()
            for row in rows:
                out[row["mid_hash"]] = {"uid": row["uid"], "uname": row["uname"],
                                        "level": row["level"]}
        if out:
            with self._lock:
                self._conn.executemany(
                    "UPDATE midhash_index SET hits = hits + 1 WHERE mid_hash = ?",
                    [(h,) for h in out])
                self._conn.commit()
        return out

    def midhash_remember(self, entries: list[dict]) -> int:
        """写入/更新 (mid_hash, uid[, uname, level])。返回处理条数。"""
        rows = []
        now = int(time.time())
        for e in entries or []:
            mid_hash = str(e.get("mid_hash") or "").strip()
            uid = e.get("uid")
            if not mid_hash or uid in (None, ""):
                continue
            try:
                uid_int = int(uid)
            except (TypeError, ValueError):
                continue
            rows.append((mid_hash, uid_int, e.get("uname"), e.get("level"),
                         e.get("source") or "unknown", now))
        if not rows:
            return 0
        with self._lock:
            self._conn.executemany(
                "INSERT INTO midhash_index(mid_hash, uid, uname, level, source, updated_at)"
                " VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(mid_hash) DO UPDATE SET"
                "   uid=excluded.uid,"
                "   uname=COALESCE(excluded.uname, midhash_index.uname),"
                "   level=COALESCE(excluded.level, midhash_index.level),"
                "   source=excluded.source,"
                "   updated_at=excluded.updated_at",
                rows)
            self._conn.commit()
        return len(rows)

    def midhash_top(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT mid_hash, uid, uname, level, source, hits FROM midhash_index"
            " ORDER BY hits DESC, updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ 多账号

    def create_account(self, alias: str, login_method: str = "qr",
                       username: str | None = None,
                       password_enc: bytes | None = None,
                       cookie_enc: bytes | None = None) -> int:
        now = int(time.time())
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO accounts(alias, login_method, username, password_enc,"
                " cookie_enc, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                (alias, login_method, username, password_enc, cookie_enc, now, now))
            self._conn.commit()
            return int(cur.lastrowid)

    def update_account(self, account_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields.setdefault("updated_at", int(time.time()))
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self._conn.execute(f"UPDATE accounts SET {cols} WHERE id=?",
                               (*fields.values(), account_id))
            self._conn.commit()

    def get_account(self, account_id: int) -> dict | None:
        row = self._conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        return dict(row) if row else None

    def get_account_by_alias(self, alias: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM accounts WHERE alias=?", (alias,)).fetchone()
        return dict(row) if row else None

    def list_accounts(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def delete_account(self, account_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
            self._conn.commit()
            return cur.rowcount > 0


class MidHashIndex:
    """给 danmaku 模块用的轻量适配器（避免 api 层直接依赖 Store）。"""

    def __init__(self, store: Store) -> None:
        self.store = store

    def lookup(self, hashes) -> dict[str, dict]:
        return self.store.midhash_lookup(hashes)

    def remember(self, entries: list[dict]) -> int:
        return self.store.midhash_remember(entries)

    def stats(self) -> dict:
        return self.store.stats()

"""批量任务队列：多 worker 并发 + 多账号绑定/分片。

并发模型
--------
* 每个 **worker 是一个线程**，从任务队列取 job 执行（`workers` 可配置）。
* 每个 job 绑定一个**账号**（不指定时自动挑一个健康账号）。
* **账号级锁**保证同一账号同时只有一个请求在跑 —— 只有不同账号才能真正并行。
  这是刻意设计：单账号并发最容易触发 bilibili 风控（-352 / 412）。
* `shard=True` 时把一个 job 的 targets 按可用账号切分，多账号并行分摊，
  同一 job 内各分片用不同账号，因此不受"同账号串行"的限制。

因此实际吞吐 ≈ `min(worker 数, 可用账号数)`。只有一个账号时，加 worker 不会提速，
但也不会更容易被风控。
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from typing import Any, Callable

from .accounts import AccountPool
from .api import BiliAPI
from .store import Store

MAX_TARGETS = 2000


def _opt(options: dict, key: str, default=None):
    value = options.get(key, default)
    if value in ("", None):
        return default
    return value


def _search(api: BiliAPI, target: str, o: dict) -> Any:
    return api.search(
        target,
        order=_opt(o, "order", "totalrank"),
        page=int(_opt(o, "page", 1)),
        page_size=int(_opt(o, "page_size", 30)),
        duration=int(_opt(o, "duration", 0)),
        pubtime_begin_s=int(o["pubtime_begin_s"]) if o.get("pubtime_begin_s") else None,
        pubtime_end_s=int(o["pubtime_end_s"]) if o.get("pubtime_end_s") else None,
        pages=int(_opt(o, "pages", 1)),
    )


def _video(api: BiliAPI, target: str, o: dict) -> Any:
    return api.video(
        target,
        with_subtitle=bool(_opt(o, "with_subtitle", True)),
        with_subtitle_text=bool(_opt(o, "with_subtitle_text", False)),
        with_tags=bool(_opt(o, "with_tags", True)),
        with_pinned_comment=bool(_opt(o, "with_pinned_comment", True)),
        with_page_probe=bool(_opt(o, "with_page_probe", False)),
    )


def _comments(api: BiliAPI, target: str, o: dict) -> Any:
    return api.comments(
        target,
        page=int(_opt(o, "page", 1)),
        page_size=int(_opt(o, "page_size", 20)),
        sort=_opt(o, "sort", "hot"),
        with_sub=bool(_opt(o, "with_sub", True)),
        sub_pages=int(_opt(o, "sub_pages", 1)),
        pages=int(_opt(o, "pages", 1)),
    )


def _danmaku(api: BiliAPI, target: str, o: dict) -> Any:
    return api.danmaku(
        target,
        segment_index=int(_opt(o, "segment_index", 0)),
        all_segments=bool(_opt(o, "all_segments", True)),
        resolve_senders=bool(_opt(o, "resolve_senders", False)),
        enrich_limit=int(_opt(o, "enrich_limit", 0)),
        pool_pages=int(_opt(o, "pool_pages", 5)),
    )


def _user(api: BiliAPI, target: str, o: dict) -> Any:
    return api.user(
        target,
        with_followings=bool(_opt(o, "with_followings", False)),
        with_followers=bool(_opt(o, "with_followers", False)),
        list_pages=int(_opt(o, "list_pages", 1)),
        with_dynamic_scan=bool(_opt(o, "with_dynamic_scan", False)),
    )


def _user_videos(api: BiliAPI, target: str, o: dict) -> Any:
    return api.user_videos(
        target,
        page=int(_opt(o, "page", 1)),
        page_size=int(_opt(o, "page_size", 30)),
        order=_opt(o, "order", "pubdate"),
        keyword=_opt(o, "keyword", ""),
        pages=int(_opt(o, "pages", 1)),
    )


def _stream(api: BiliAPI, target: str, o: dict) -> Any:
    return api.stream(target, qn=int(_opt(o, "qn", 80)), fnval=int(_opt(o, "fnval", 4048)))


def _dynamics(api: BiliAPI, target: str, o: dict) -> Any:
    return api.dynamics(target, page=int(_opt(o, "page", 1)),
                        offset=_opt(o, "offset", ""),
                        pages=int(_opt(o, "pages", 1)))


KINDS: dict[str, Callable[[BiliAPI, str, dict], Any]] = {
    "search": _search,
    "video": _video,
    "comments": _comments,
    "danmaku": _danmaku,
    "user": _user,
    "user_videos": _user_videos,
    "stream": _stream,
    "dynamics": _dynamics,
}

KIND_LABEL = {
    "search": "2.1 综合搜索",
    "video": "2.2 视频详情",
    "comments": "2.3 视频评论",
    "danmaku": "2.4 视频弹幕",
    "user": "2.5 用户资料",
    "user_videos": "2.6 作者视频列表",
    "stream": "2.7 视频流",
    "dynamics": "2.8 用户动态",
}


class JobRunner:
    """多 worker 任务执行器。"""

    def __init__(self, pool: AccountPool, store: Store, workers: int = 3) -> None:
        self.pool = pool
        self.store = store
        self.workers = max(1, int(workers))
        self._queue: "queue.Queue[int]" = queue.Queue()
        self._cancelled: set[int] = set()
        self._lock = threading.Lock()          # 保护 _cancelled / 计数
        self._active: dict[int, str] = {}      # job_id -> 运行中的账号描述
        self._threads: list[threading.Thread] = []
        # 进程重启后，上一进程遗留的 running/pending 不可能还在跑：先落成 interrupted，
        # 否则界面会一直挂着僵尸"运行中"任务。放在起 worker 之前，避免与执行竞争。
        try:
            stale = self.store.mark_stale_jobs_interrupted()
            if stale:
                print(f"[biliwb] 已把 {stale} 个进程重启前遗留的任务标记为 interrupted",
                      file=__import__("sys").stderr)
        except Exception as exc:  # noqa: BLE001
            print(f"[biliwb] 清理遗留任务失败: {type(exc).__name__}: {exc}",
                  file=__import__("sys").stderr)
        self._start()

    # ------------------------------------------------------------ 生命周期

    def _start(self) -> None:
        for i in range(self.workers):
            t = threading.Thread(target=self._loop, name=f"biliwb-worker-{i + 1}", daemon=True)
            t.start()
            self._threads.append(t)

    def _loop(self) -> None:
        while True:
            job_id = self._queue.get()
            if job_id == -1:            # 缩减 worker 时的哨兵，让线程干净退出
                self._queue.task_done()
                return
            try:
                self._execute(job_id)
            except Exception as exc:  # noqa: BLE001
                print(f"!!! worker 执行任务 {job_id} 崩溃: {type(exc).__name__}: {exc}",
                      file=__import__("sys").stderr)
                traceback.print_exc()
                self.store.update_job(job_id, status="failed",
                                      error=f"{type(exc).__name__}: {exc}",
                                      finished_at=int(time.time()))
            finally:
                with self._lock:
                    self._active.pop(job_id, None)
                self._queue.task_done()

    def set_workers(self, n: int) -> dict:
        """运行时调整 worker 数（增：直接起线程；减：投哨兵让多余线程退出）。"""
        n = max(1, min(int(n), 32))
        old = self.workers
        self.workers = n
        if n > old:
            for _ in range(n - old):
                t = threading.Thread(target=self._loop,
                                     name=f"biliwb-worker-{len(self._threads) + 1}",
                                     daemon=True)
                t.start()
                self._threads.append(t)
        elif n < old:
            for _ in range(old - n):
                self._queue.put(-1)
        return self.workers_status()

    def workers_status(self) -> dict:
        with self._lock:
            active = dict(self._active)
        return {
            "workers": self.workers,
            "queued": self._queue.qsize(),
            "running": len(active),
            "active_jobs": active,
            "threads_alive": sum(1 for t in self._threads if t.is_alive()),
        }

    # ------------------------------------------------------------ 提交

    def submit(self, kind: str, targets: list[str], options: dict | None = None,
               account_id: int | None = None, shard: bool = False) -> int:
        if kind not in KINDS:
            raise ValueError(f"未知任务类型: {kind}，可选 {list(KINDS)}")
        cleaned = [str(t).strip() for t in targets if str(t).strip()]
        if not cleaned:
            raise ValueError("targets 不能为空")
        if len(cleaned) > MAX_TARGETS:
            raise ValueError(f"单次任务最多 {MAX_TARGETS} 个目标")
        if account_id is not None and not self.store.get_account(account_id):
            raise ValueError(f"账号不存在: {account_id}")
        job_id = self.store.create_job(kind, cleaned, options or {},
                                       account_id=account_id, shard=shard)
        self._queue.put(job_id)
        return job_id

    def cancel(self, job_id: int) -> None:
        with self._lock:
            self._cancelled.add(job_id)

    def _is_cancelled(self, job_id: int) -> bool:
        with self._lock:
            return job_id in self._cancelled

    # ------------------------------------------------------------ 执行

    def _execute(self, job_id: int) -> None:
        job = self.store.get_job(job_id)
        if not job:
            return
        if job["status"] not in ("pending", "running"):
            return

        targets = job["targets"]
        if job.get("shard"):
            accounts = self.pool.healthy_ids()
            if len(accounts) > 1:
                self._execute_sharded(job, accounts)
                return
            # 可用账号不足 2 个时分片没有意义
            self.store.update_job(job_id, shard=0)

        self._execute_single(job, targets, account_id=job.get("account_id"))

    def _execute_single(self, job: dict, targets: list[str],
                        account_id: int | None) -> None:
        job_id = job["id"]
        if account_id is None:
            account_id = self.pool.pick()
        if account_id is None:
            self.store.update_job(job_id, status="failed",
                                  error="没有可用账号：请先在「账号」里添加并校验",
                                  finished_at=int(time.time()))
            return

        alias = (self.store.get_account(account_id) or {}).get("alias", str(account_id))
        with self._lock:
            self._active[job_id] = f"{alias} (账号 {account_id})"
        self.store.update_job(job_id, status="running", account_id=account_id)

        api = self.pool.api(account_id)
        acct_lock = self.pool.lock(account_id)
        fn = KINDS[job["kind"]]
        options = job["options"]

        done_set = self.store.completed_targets(job_id)
        finished, failed = len(done_set), 0
        self.store.update_job(job_id, done=finished)

        for target in targets:
            if self._is_cancelled(job_id):
                self.store.update_job(job_id, status="cancelled",
                                      finished_at=int(time.time()))
                return
            if target in done_set:
                continue
            try:
                with acct_lock:      # 同账号串行，避免风控
                    payload = fn(api, target, options)
                self.store.add_result(job_id, target, True, payload)
                self.store.save_record(job["kind"], target, payload)
                finished += 1
            except Exception as exc:  # noqa: BLE001
                failed += 1
                detail = f"{type(exc).__name__}: {exc}"
                print(f"[job {job_id}][{alias}] {job['kind']} {target} 失败: {detail}",
                      file=__import__("sys").stderr)
                self.store.add_result(job_id, target, False, None, detail)
            self.store.update_job(job_id, done=finished, failed=failed)

        self.store.update_job(job_id, status="finished", done=finished,
                              failed=failed, finished_at=int(time.time()))

    def _execute_sharded(self, job: dict, accounts: list[int]) -> None:
        """把 targets 按账号切分并行跑（各分片用不同账号）。"""
        job_id = job["id"]
        targets = job["targets"]
        buckets: dict[int, list[str]] = {a: [] for a in accounts}
        for i, target in enumerate(targets):
            buckets[accounts[i % len(accounts)]].append(target)

        self.store.update_job(job_id, status="running", shard=1)
        with self._lock:
            self._active[job_id] = f"分片到 {len(accounts)} 个账号"

        counters = {"done": 0, "failed": 0}
        counter_lock = threading.Lock()

        def run_shard(account_id: int, sub: list[str]) -> None:
            alias = (self.store.get_account(account_id) or {}).get("alias", str(account_id))
            api = self.pool.api(account_id)
            acct_lock = self.pool.lock(account_id)
            fn = KINDS[job["kind"]]
            options = job["options"]
            done_set = self.store.completed_targets(job_id)
            for target in sub:
                if self._is_cancelled(job_id):
                    return
                if target in done_set:
                    with counter_lock:
                        counters["done"] += 1
                    continue
                try:
                    with acct_lock:
                        payload = fn(api, target, options)
                    self.store.add_result(job_id, target, True, payload)
                    self.store.save_record(job["kind"], target, payload)
                    with counter_lock:
                        counters["done"] += 1
                except Exception as exc:  # noqa: BLE001
                    detail = f"{type(exc).__name__}: {exc}"
                    print(f"[job {job_id}][{alias}] {job['kind']} {target} 失败: {detail}",
                          file=__import__("sys").stderr)
                    self.store.add_result(job_id, target, False, None, detail)
                    with counter_lock:
                        counters["failed"] += 1
                with counter_lock:
                    # 快照与写回必须在同一把锁内：否则两个分片会各自读到旧快照，
                    # 后写的那个把 done 计数覆盖回去（实测导致 done 少算）。
                    snapshot = dict(counters)
                    self.store.update_job(job_id, done=snapshot["done"],
                                          failed=snapshot["failed"])

        threads = [threading.Thread(target=run_shard, args=(acc, sub), daemon=True)
                   for acc, sub in buckets.items() if sub]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if self._is_cancelled(job_id):
            self.store.update_job(job_id, status="cancelled", finished_at=int(time.time()))
            return
        self.store.update_job(job_id, status="finished",
                              done=counters["done"], failed=counters["failed"],
                              finished_at=int(time.time()))

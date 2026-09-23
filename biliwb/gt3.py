"""GT3 验证码解算桥接（密码登录用）。

纯 Python 通过极验 GT3 文字点选，不需要浏览器。实现在既有任务目录里：

    js_reverse_cache/tasks/bili-gt3-solver/
        gt3_protocol.py          协议驱动（子进程入口）
        env/run.js               node:vm + env-patch 跑极验原始资产
        gt3_click_solve_v11.py   点选求解器
        patch_*.py               最小补丁（导出内部 widget 方法）

一次运行的输出里同时含两组关键字段，正好是密码登录要提交的：

    [round] gt=<gt> challenge=<challenge> token=<token>
    === SUCCESS validate=<validate> score=<score> ===

登录提交用：validate / seccode / challenge / token
（GT3 惯例 seccode = "<validate>|jordan"）

成本与风险（实测口径）
----------------------
* 单轮耗时约 30~60 秒（node 里跑完整极验流程 + 本地 OCR 求解）
* 成功率不是 100%；失败时会输出 [verdict] 说明原因
* 因此**日常用 cookie 复用**，只在 cookie 失效时才走密码登录
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_SOLVER_DIR = ROOT / "js_reverse_cache" / "tasks" / "bili-gt3-solver"

ROUND_RE = re.compile(r"\[round\]\s*gt=(\S+)\s+challenge=(\S+)\s+token=(\S+)")
SUCCESS_RE = re.compile(r"=== SUCCESS validate=(\S+) score=(\S+) ===")
VERDICT_RE = re.compile(r"\[verdict\].*?->\s*(\{.*\})\s*$", re.M)


class Gt3Unavailable(RuntimeError):
    """解算器缺失或依赖不全（我方环境问题，不是目标站问题）。"""


def solver_ready(task_dir: pathlib.Path | None = None) -> dict:
    """检查解算器是否可用（不发起任何请求）。"""
    d = pathlib.Path(task_dir or DEFAULT_SOLVER_DIR)
    out = {
        "dir": str(d),
        "protocol": (d / "gt3_protocol.py").exists(),
        "helper_js": (d / "env" / "run.js").exists(),
        "solver_v11": (d / "gt3_click_solve_v11.py").exists(),
        "patched_core": (d / "cache" / "fullpage.patched-core.js").exists(),
        "patched_click": (d / "cache" / "click.patched-widget.js").exists(),
    }
    missing_py = []
    for mod in ("ddddocr", "cv2", "numpy"):
        try:
            __import__(mod)
        except Exception:
            missing_py.append(mod)
    out["missing_python_modules"] = missing_py

    node_ok = False
    try:
        proc = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=10)
        node_ok = proc.returncode == 0
        out["node_version"] = (proc.stdout or "").strip()
    except Exception:
        out["node_version"] = None
    out["node"] = node_ok

    out["ready"] = (out["protocol"] and out["helper_js"] and out["solver_v11"]
                    and node_ok and not missing_py)
    return out


def solve_once(
    source: str = "main-fe",
    task_dir: pathlib.Path | None = None,
    timeout: int = 600,
    max_http: int = 40,
    helper_rounds: int = 80,
    timer_cap: int = 2000,
    gt: str | None = None,
    challenge: str | None = None,
    token: str | None = None,
    cookies: str | None = None,
) -> dict:
    """跑一轮 GT3，返回一组可直接用于密码登录的字段。

    `gt`/`challenge`/`token` 传入时不再自行预取验证码 —— passport 把 token 绑定在
    **预取它的那个会话**上，所以必须由即将提交登录的同一个 client 预取后传进来。

    返回：{ok, gt, challenge, token, validate, seccode, score, seconds, verdict, log_tail}

    `max_http` 是子进程的请求上限：一轮点选正常 10~11 次，而极验判决失败时会自动
    再来一轮（同 challenge），所以上限必须留出多轮余量，否则会以"未取得 validate"
    的形式无谓失败。
    """
    d = pathlib.Path(task_dir or DEFAULT_SOLVER_DIR)
    readiness = solver_ready(d)
    if not readiness["ready"]:
        raise Gt3Unavailable(f"GT3 解算器不可用: {readiness}")

    cmd = [
        sys.executable, str(d / "gt3_protocol.py"),
        "--source", source,
        "--max-http", str(max_http),
        "--patched-core", "--patched-click",
        "--call-widget", "$_BJJQ",
        "--answer-format", "pct",
        "--verify-first",
        "--timer-cap", str(timer_cap),
        "--helper-rounds", str(helper_rounds),
    ]
    if gt and challenge:
        cmd += ["--gt", gt, "--challenge", challenge]
        if token:
            cmd += ["--token", token]
    if cookies:
        cmd += ["--cookies", cookies]
    # 协议进程内部的墙钟预算与父进程的 kill 超时保持一致，日志里能看出是"预算用尽"
    cmd += ["--deadline", str(max(15.0, float(timeout) - 3.0))]
    started = time.time()
    try:
        proc = subprocess.run(cmd, cwd=str(d), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "seconds": round(time.time() - started, 1),
                "error": f"解算超时（>{timeout}s）"}
    log = (proc.stdout or "") + "\n" + (proc.stderr or "")

    rounds = ROUND_RE.findall(log)
    success = SUCCESS_RE.search(log)
    verdicts = VERDICT_RE.findall(log)

    # 预取模式下以调用方传入的一对为准：日志里 token 可能被截断/为空。
    issued_challenge, issued_token = challenge, token
    if rounds:
        # 取最后一次（与最终 verdict 同轮）
        log_gt, log_challenge, log_token = rounds[-1]
        gt = gt or log_gt
        issued_challenge = issued_challenge or log_challenge
        issued_token = issued_token or log_token

    validate = success.group(1) if success else None
    result = {
        "ok": bool(validate and issued_challenge and issued_token),
        "gt": gt,
        "challenge": issued_challenge,
        "token": issued_token,
        "validate": validate,
        "seccode": f"{validate}|jordan" if validate else None,
        "score": success.group(2) if success else None,
        "verdict": verdicts[-1] if verdicts else None,
        "rounds_seen": len(rounds),
        "seconds": round(time.time() - started, 1),
        "http_used": _http_used(log),
        "log_tail": [ln.strip() for ln in log.splitlines()
                     if "[verdict]" in ln or "SUCCESS" in ln or "[round]" in ln][-6:],
    }
    if not validate:
        # 失败原因必须能看见：极验的最终判决就在 ajax.php 的 verdict 里
        why = "未取得 validate（求解失败）"
        if result["verdict"]:
            why += f"；极验判决: {result['verdict']}"
        if proc.returncode != 0:
            why += f"；解算器退出码 {proc.returncode}"
        result["error"] = why
    return result


def _http_used(log: str) -> int | None:
    m = re.search(r"=== http used:\s*(\d+)", log)
    return int(m.group(1)) if m else None


if __name__ == "__main__":
    import json

    print(json.dumps(solver_ready(), ensure_ascii=False, indent=2))

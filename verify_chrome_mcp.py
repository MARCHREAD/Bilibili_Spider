"""Standalone MCP handshake check for the chrome-devtools MCP server.

Spawns the exact command from cordis.patch.yml over stdio and performs
initialize + tools/list. No target egress, no browser navigation: the Chrome
instance is only launched when a browser tool is actually called.
Prints tool names to stderr; machine JSON to stdout.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time

NODE = "node"
BIN = r"C:\Users\20240\AppData\Roaming\npm\node_modules\chrome-devtools-mcp\build\src\bin\chrome-devtools-mcp.js"
ARGS = [BIN, "--isolated", "--viewport", "1280x900", "--no-usage-statistics"]


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    proc = subprocess.Popen(
        [NODE, *ARGS],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    incoming: list[dict] = []
    stderr_lines: list[str] = []
    lock = threading.Lock()

    def pump_stdout() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            with lock:
                incoming.append(msg)

    threading.Thread(target=pump_stdout, daemon=True).start()

    def pump_stderr() -> None:
        for line in proc.stderr:  # type: ignore[union-attr]
            with lock:
                stderr_lines.append(line.rstrip())

    threading.Thread(target=pump_stderr, daemon=True).start()

    def send(obj: dict) -> None:
        assert proc.stdin
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def wait_for(msg_id: int, timeout: float = 45.0) -> dict | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            with lock:
                for msg in incoming:
                    if msg.get("id") == msg_id:
                        return msg
            time.sleep(0.2)
        return None

    result: dict = {"command": f"{NODE} {' '.join(ARGS[:1])}", "ok": False}
    try:
        send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "spider-king-verify", "version": "1.0"},
                },
            }
        )
        init = wait_for(1)
        if init is None:
            result["error"] = "initialize timed out"
        else:
            result["serverInfo"] = (init.get("result") or {}).get("serverInfo")
            result["protocolVersion"] = (init.get("result") or {}).get("protocolVersion")
            send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
            send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
            tools_msg = wait_for(2, timeout=60)
            if tools_msg is None:
                result["error"] = "tools/list timed out"
            else:
                tools = ((tools_msg.get("result") or {}).get("tools")) or []
                result["tool_count"] = len(tools)
                result["tools"] = [t.get("name") for t in tools]
                result["ok"] = True
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()

    result["stderr_head"] = stderr_lines[:6]
    with lock:
        result["stderr_tail"] = stderr_lines[-6:]

    if result.get("tools"):
        note("=== chrome-devtools MCP tools ===")
        for name in result["tools"]:
            note(f"  mcp__chrome__{name}")
    note(f"ok={result['ok']} serverInfo={result.get('serverInfo')} count={result.get('tool_count')}")
    print(json.dumps({k: v for k, v in result.items() if k != "tools"}, ensure_ascii=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

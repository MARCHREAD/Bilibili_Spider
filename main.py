"""bilibili 本地批量采集工作台 —— 右键运行入口（无需任何命令行参数）。

直接运行本文件即可：
    * 启动本地工作台服务（默认 http://127.0.0.1:8765/）
    * 自动打开浏览器
    * 页面里扫码登录后即可使用 8 项采集能力与批量任务

可选参数：
    --port 8766        换端口
    --no-browser       不自动开浏览器
    --selftest         只跑离线自检（不联网、不需要登录）
"""

from __future__ import annotations

import argparse
import runpy
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_selftest() -> int:
    script = ROOT / "tests" / "test_local_proofs.py"
    if not script.exists():
        print(f"找不到自检脚本: {script}", file=sys.stderr)
        return 2
    runpy.run_path(str(script), run_name="__main__")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="bilibili 本地采集工作台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--selftest", action="store_true",
                        help="只运行离线自检（不启动服务）")
    args = parser.parse_args()

    if args.selftest:
        return run_selftest()

    try:
        import uvicorn
    except ImportError as exc:
        print(f"缺少依赖 uvicorn: {exc}\n请先执行: pip install -r requirements.txt",
              file=sys.stderr)
        return 2

    from biliwb.server import create_app

    app = create_app(ROOT / "data")
    url = f"http://{args.host}:{args.port}/"

    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    print("=" * 62)
    print(" bilibili 本地批量采集工作台")
    print(f" 控制台地址: {url}")
    print(f" 数据目录  : {ROOT / 'data'}")
    print(" 停止服务  : 在本窗口按 Ctrl+C")
    print("=" * 62)

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
    except KeyboardInterrupt:
        print("\n已停止。")
    except OSError as exc:
        print(f"启动失败（端口可能被占用）: {exc}\n可换端口: python main.py --port 8766",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""接口调用追踪与 CSV 导出的离线回归。"""

from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from biliwb.client import BiliClient
from biliwb.server import _results_csv


class FakeResponse:
    status_code = 200


def main() -> int:
    client = BiliClient(min_delay=0, jitter=0)
    client.session.request = lambda *args, **kwargs: FakeResponse()
    client.begin_trace()
    client._raw("GET", "https://api.bilibili.com/x/test?token=SECRET")
    trace = client.end_trace()

    assert len(trace) == 1
    assert trace[0]["endpoint"] == "/x/test"
    assert "SECRET" not in str(trace)
    assert trace[0]["status"] == 200
    assert trace[0]["duration_ms"] >= 0

    content = _results_csv([{
        "target": "demo",
        "ok": 1,
        "error": None,
        "duration_ms": 12.3,
        "payload": {"items": [{"title": "=formula", "play": 42}]},
    }])
    assert content.startswith("\ufeff")
    assert "target,ok,error,duration_ms,title,play" in content
    assert "'=formula" in content
    print("observability: 8 passed, 0 failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

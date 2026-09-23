"""Extract the JSONP requester body and its decodable string indices. Local only."""
from __future__ import annotations

import pathlib
import re
import sys

ASSET = pathlib.Path(__file__).resolve().parent / "cache" / "fullpage.9.2.0-guwyxh.js"
START = 96550
SPAN = 3200


def main() -> int:
    text = ASSET.read_text(encoding="utf-8", errors="replace")
    body = text[START:START + SPAN]
    indices = sorted({int(m.group(1)) for m in re.finditer(r"\((\d{2,4})\)", body)})
    pathlib.Path(__file__).resolve().parent.joinpath("requester_body.txt").write_text(body, encoding="utf-8")
    print(",".join(str(i) for i in indices))
    print("---", file=sys.stderr)
    print(body, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

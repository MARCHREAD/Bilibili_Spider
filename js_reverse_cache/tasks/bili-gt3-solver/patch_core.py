"""Create a minimal core-export patch of the raw fullpage asset.

The workflow reference (references/captcha/geetest-gt3-workflow.md) captures the
fullpage core from the `new nt(t)` assignment. This script rewrites exactly that
assignment to also publish the instance on globalThis, and writes a manifest with
both hashes. The raw asset stays untouched; the helper loads the patched copy.

Local only.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

TASK = pathlib.Path(__file__).resolve().parent
RAW = TASK / "cache" / "fullpage.9.2.0-guwyxh.js"
PATCHED = TASK / "cache" / "fullpage.patched-core.js"
NEEDLE = "=new nt("


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    text = RAW.read_text(encoding="utf-8", errors="replace")
    occurrences = text.count(NEEDLE)
    if occurrences != 1:
        note(f"[fail] expected exactly one {NEEDLE!r}, found {occurrences}")
        return 1
    idx = text.index(NEEDLE)
    patched = text[:idx] + "=globalThis.__gt3Core=new nt(" + text[idx + len(NEEDLE):]

    # sanity: exactly one global export added, nothing else changed
    delta = len(patched) - len(text)
    PATCHED.write_text(patched, encoding="utf-8")
    manifest = {
        "raw": RAW.name,
        "raw_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "patched": PATCHED.name,
        "patched_sha256": hashlib.sha256(patched.encode()).hexdigest(),
        "needle": NEEDLE,
        "needle_offset": idx,
        "size_delta": delta,
        "inserted": "globalThis.__gt3Core=",
        "context": text[max(0, idx - 120):idx + 120],
    }
    (TASK / "cache" / "fullpage_patch_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    note(f"[ok] patched copy written, delta={delta}B raw={manifest['raw_sha256'][:12]} patched={manifest['patched_sha256'][:12]}")
    print(json.dumps({k: v for k, v in manifest.items() if k != "context"}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

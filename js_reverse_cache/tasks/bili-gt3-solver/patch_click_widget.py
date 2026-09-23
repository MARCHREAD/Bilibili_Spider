"""Patch the click product so the internal widget object becomes reachable.

Two minimal, behaviour-preserving injections:
  1. in the requester `function R(e,t,n){` -> capture the context object it is called with
  2. in the widget class literal `Be[$_CGAs(270)]={...}` -> capture `this` at the top of
     every method, so whichever method runs first publishes the live widget instance
     (the widget owns the round state and the submission method `$_BJJQ`)

Raw asset untouched; hashes recorded.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

TASK = pathlib.Path(__file__).resolve().parent
RAW = TASK / "cache" / "click.3.1.2.js"
PATCHED = TASK / "cache" / "click.patched-widget.js"

R_NEEDLE = "function R(e,t,n){"
R_INJECT = "globalThis.__gt3Ctx=globalThis.__gt3Ctx||e;"
LIT_NEEDLE = re.compile(r'\[\$_CGAs\(270\)\]=\{')
METHOD_RE = re.compile(r'("(?:\\u[0-9a-fA-F]{4})+":function\([^)]*\)\{)')


def note(msg: str) -> None:
    print(msg.encode("utf-8", "replace").decode("utf-8", "replace"), file=sys.stderr, flush=True)


def main() -> int:
    text = RAW.read_text(encoding="utf-8", errors="replace")
    patched = text
    report: dict = {}

    # 1) requester context
    if R_NEEDLE in patched:
        idx = patched.index(R_NEEDLE)
        patched = patched[:idx + len(R_NEEDLE)] + R_INJECT + patched[idx + len(R_NEEDLE):]
        report["requester_inject_at"] = idx
    else:
        note("[warn] requester needle missing")

    # 2) widget literal methods. `[$_CGAs(270)]={` is the shared prototype slot for
    # several classes, so pick the literal that actually defines the submission
    # method ($_BJJQ) and patch that one.
    bjjq_escaped = "\\u0024\\u005f\\u0042\\u004a\\u004a\\u0051"
    candidates = [mm.start() for mm in LIT_NEEDLE.finditer(patched)]
    start = end = None
    for cand in candidates:
        depth = 0
        for j in range(cand, len(patched)):
            if patched[j] == "{":
                depth += 1
            elif patched[j] == "}":
                depth -= 1
                if depth == 0:
                    if bjjq_escaped in patched[cand:j + 1]:
                        start, end = cand, j
                    break
        if start is not None:
            break
    if start is None or end is None:
        note("[fail] widget literal with $_BJJQ not found")
        return 1
    body = patched[start:end + 1]
    new_body, n = METHOD_RE.subn(lambda mm: mm.group(1) + "globalThis.__gt3Widget=this;", body)
    patched = patched[:start] + new_body + patched[end + 1:]
    report.update({
        "literal_candidates": len(candidates),
        "literal_start": start,
        "literal_len": len(body),
        "methods_injected": n,
        "size_delta": len(patched) - len(text),
    })

    # 3) expose the submission plaintext right before it is encrypted
    # must be a statement BEFORE the var declarator list: inserting into
    # "var u=...,h=..." yields "var u=...,globalThis.x=o,h=..." which is a
    # SyntaxError (Unexpected token '.') and silently kills the whole asset.
    PLAIN_NEEDLE = "var u=n[$_CADAp(751)](),h=X[$_CADBN(374)]"
    PLAIN_INJECT = "globalThis.__gt3Plain=o;"
    if PLAIN_NEEDLE in patched:
        k = patched.index(PLAIN_NEEDLE)
        patched = patched[:k] + PLAIN_INJECT + patched[k:]
        report["plain_inject_at"] = k
    else:
        note("[warn] plaintext needle missing")

    PATCHED.write_text(patched, encoding="utf-8")
    manifest = {
        "raw": RAW.name,
        "raw_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "patched": PATCHED.name,
        "patched_sha256": hashlib.sha256(patched.encode()).hexdigest(),
        **report,
    }
    (TASK / "cache" / "click_patch_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2), encoding="utf-8"
    )
    note(f"[ok] patched: methods_injected={n} delta={report['size_delta']}B "
         f"patched_sha={manifest['patched_sha256'][:12]}")
    print(json.dumps(manifest, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

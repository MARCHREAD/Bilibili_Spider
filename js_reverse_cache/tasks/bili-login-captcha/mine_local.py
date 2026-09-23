"""Local-only mining: chunk manifest + homepage captcha markers. No egress."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

TASK = Path(__file__).resolve().parent
RAW = TASK / "raw"


def note(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def windows(text: str, needle: str, width: int = 180, limit: int = 8, flags=re.I) -> list[str]:
    out, seen = [], set()
    for m in re.finditer(needle, text, flags):
        snippet = text[max(0, m.start() - width) : m.end() + width].replace("\n", " ")
        if snippet[:70] in seen:
            continue
        seen.add(snippet[:70])
        out.append(f"@{m.start()} ...{snippet}...")
        if len(out) >= limit:
            break
    return out


def main() -> int:
    bundle = (RAW / "index.ed509056.js").read_text(encoding="utf-8", errors="replace")
    home = (RAW / "home.html").read_text(encoding="utf-8", errors="replace")
    report: dict = {}

    # --- chunk manifest shapes (rsbuild/webpack runtime) ---
    report["all_js_strings"] = sorted(set(re.findall(r"[\"'`]([A-Za-z0-9_\-./]*\.js)[\"'`]", bundle)))[:80]
    report["static_js_paths"] = sorted(set(re.findall(r"[\"'`]([^\"'`]*static/js/[^\"'`]+)[\"'`]", bundle)))[:80]
    report["hash_maps"] = re.findall(r"\{[0-9]{2,4}:\"[0-9a-f]{6,}\"(?:,[0-9]{2,4}:\"[0-9a-f]{6,}\"){2,}\}", bundle)[:5]
    report["u_fn"] = windows(bundle, r"\.u\s*=\s*function|\.u\s*=\s*[a-zA-Z]\s*=>", width=420, limit=4)

    # --- routing / api path literals ---
    report["api_paths"] = sorted(set(re.findall(r"[\"'`](/x/[A-Za-z0-9_/\-{}]+)", bundle)))[:80]
    report["passport_words"] = sorted(set(re.findall(r"passport[A-Za-z0-9_/\-]*", bundle, re.I)))[:40]

    # --- homepage captcha markers ---
    report["home_geetest"] = windows(home, "geetest")
    report["home_login_scripts"] = sorted(set(re.findall(r"https?://[^\"'<> ]+\.js", home)))[:40]
    report["home_risk_words"] = len(re.findall(r"risk|captcha", home, re.I))

    (TASK / "local_mine.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for k in ("all_js_strings", "static_js_paths", "hash_maps", "api_paths", "passport_words"):
        note(f"=== {k} ===")
        for v in report[k]:
            note(f"  {str(v)[:300]}")
    for k in ("u_fn", "home_geetest"):
        note(f"=== {k} ===")
        for v in report[k]:
            note(f"  {v}")
    note(f"=== home_login_scripts ({len(report['home_login_scripts'])}) ===")
    for v in report["home_login_scripts"]:
        note(f"  {v}")

    print(json.dumps({k: len(v) if isinstance(v, list) else v for k, v in report.items()}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

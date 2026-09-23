"""按 github-slugger 的规则校验 README 的目录锚点与表格结构。"""

import pathlib
import re
import unicodedata


def slug(heading: str) -> str:
    """近似 github-slugger：保留 L/N/M/Pc/-/空格，其余剔除，空格转 '-'。"""
    s = heading.lstrip("#").strip().lower()
    keep = []
    for ch in s:
        cat = unicodedata.category(ch)
        if ch.isalnum() or ch in "- _" or cat in ("Mn", "Mc", "Me", "Pc"):
            keep.append(ch)
        elif ch == " ":
            keep.append(" ")
    return "".join(keep).replace(" ", "-")


lines = pathlib.Path("README.md").read_text(encoding="utf-8").splitlines()

heads = {slug(l) for l in lines if re.match(r"^#{1,6} ", l)}
toc = re.findall(r"\]\(#([^)]+)\)", "\n".join(lines))
unresolved = [a for a in toc if a not in heads]
print("目录锚点 %d 个 | 未解析: %s" % (len(toc), unresolved or "无"))

bad = []
for i, l in enumerate(lines):
    if l.strip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
        hdr = l.count("|")
        sep = lines[i + 1].count("|")
        if hdr != sep:
            bad.append((i + 1, hdr, sep))
        j = i + 2
        while j < len(lines) and lines[j].strip().startswith("|"):
            if lines[j].count("|") != hdr:
                bad.append((j + 1, lines[j].count("|"), hdr))
            j += 1
print("表格列数问题:", bad or "无")

fence = "`" * 3
n = sum(1 for l in lines if l.strip().startswith(fence))
print("代码围栏:", n, "->", "成对" if n % 2 == 0 else "**未闭合**")

for tag in ("div", "details", "summary", "table", "tr", "td"):
    o = len(re.findall(r"<%s[ >]" % tag, "\n".join(lines)))
    c = len(re.findall(r"</%s>" % tag, "\n".join(lines)))
    if o or c:
        print("<%s>: open=%d close=%d %s" % (tag, o, c, "OK" if o == c else "MISMATCH"))

# 敏感信息扫描
print()
sensitive = {
    "手机号": r"1[3-9]\d{9}",
    "SESSDATA": r"SESSDATA",
    "bili_jct": r"bili_jct",
    "cookie 串": r"buvid3=[0-9A-Fa-f-]{10,}",
    "密钥文件": r"\.secret\.key",
}
for name, pat in sensitive.items():
    hits = [i for i, l in enumerate(lines, 1) if re.search(pat, l)]
    print("  敏感扫描 %-10s %s" % (name, hits if hits else "无"))

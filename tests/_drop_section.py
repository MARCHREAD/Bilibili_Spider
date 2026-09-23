import pathlib
import re

p = pathlib.Path("README.md")
lines = p.read_text(encoding="utf-8").splitlines()

TITLE = "## 📊 登录依赖对照表"
TOC = "- [📊 登录依赖对照表](#-登录依赖对照表)"

out, skipping, removed = [], False, 0
for line in lines:
    if line.startswith(TITLE):
        skipping = True
        removed += 1
        continue
    if skipping:
        if line.startswith("## "):
            skipping = False          # 到达下一章，结束跳过（含本章尾部的 --- 分隔符）
        else:
            removed += 1
            continue
    if line.strip() == TOC:
        removed += 1
        continue
    out.append(line)

text = "\n".join(out)
text = re.sub(r"\n{4,}", "\n\n\n", text).rstrip() + "\n"
p.write_text(text, encoding="utf-8")
print("已删除 %d 行（章节 + 目录项）" % removed)
print("剩余 h2 章节:")
for i, line in enumerate(text.splitlines(), 1):
    if line.startswith("## "):
        print("  ", line)

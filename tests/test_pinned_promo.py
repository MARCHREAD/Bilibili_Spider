"""置顶评论 / 带货链接 / 作者归属 的离线回归测试。

固定向量：js_reverse_cache/tasks/bili-workbench/fixtures/pinned_comment_goods.json
（BV1Pg8Z62E3C 的真实响应裁剪，公开评论数据，不含任何凭证）

覆盖三个曾经真实存在的缺陷：
  B1  `data.top` 是容器 {admin, upper, vote}，不是评论对象 —— 直接取 rpid 会
      永远判成"没有置顶评论"；
  B2  `member.mid` 是字符串、`owner.mid` 是整数 —— 不归一化比较会恒为 False，
      导致"置顶评论是否作者本人"永远判错；
  B3  带货链接的权威来源是 `content.jump_url`，只靠正文正则找 URL 会漏；
      而商品卡片自带的 is_ad_loc/creative_id 曾因宽泛 except 吞掉 NameError 而为空。

用法：python tests/test_pinned_promo.py
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb.ad import judge_promo  # noqa: E402
from biliwb.api.comment import extract_pinned  # noqa: E402
from biliwb.utils import extract_comment_links, normalize_mid  # noqa: E402

FIXTURE = ROOT / "js_reverse_cache" / "tasks" / "bili-workbench" / "fixtures" / "pinned_comment_goods.json"

PASS = 0
FAIL = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label} {detail}")


def main() -> int:
    if not FIXTURE.exists():
        print(f"缺少 fixture: {FIXTURE}", file=sys.stderr)
        return 2
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    up_mid = fx["up_mid"]

    # ---------- B1: 置顶评论必须能从 top.upper 取出
    print("[B1] data.top 是容器，置顶评论在 top.upper")
    data = {"top": fx["top_container"], "top_replies": fx["top_replies"]}
    pinned = extract_pinned(data)
    check("extract_pinned 取到置顶评论", pinned is not None)
    check("来源标记为 top.upper", (pinned or {}).get("pinned_source") == "top.upper",
          str((pinned or {}).get("pinned_source")))
    check("rpid 正确", (pinned or {}).get("rpid") == 315741109936)
    check("pinned 标记为 True", (pinned or {}).get("pinned") is True)

    # 关键反例：容器本身没有 rpid，不应被当成评论
    check("负对照：容器 data.top 本身不是评论",
          not (fx["top_container"].get("rpid") if isinstance(fx["top_container"], dict) else True))

    print("[B1] 兜底与老结构")
    only_refs = {"top": {"upper": None, "admin": None, "vote": None},
                 "top_replies": fx["top_replies"]}
    check("top 为空时回退 top_replies",
          (extract_pinned(only_refs) or {}).get("pinned_source") == "top_replies")
    legacy = {"top": fx["top_container"]["upper"]}
    check("老结构(top 直接是评论)兼容",
          (extract_pinned(legacy) or {}).get("pinned_source") == "top")
    check("确实没有置顶时返回 None",
          extract_pinned({"top": {"upper": None, "admin": None}, "top_replies": []}) is None)
    check("空响应返回 None", extract_pinned({}) is None)

    # ---------- B2: mid 类型归一化
    print("[B2] mid 类型：接口给字符串，view 给整数")
    raw_mid = fx["top_container"]["upper"]["member"]["mid"]
    check("fixture 里原始 mid 是字符串", isinstance(raw_mid, str), repr(raw_mid))
    check("normalize_mid 转成 int", normalize_mid(raw_mid) == up_mid,
          f"{normalize_mid(raw_mid)!r}")
    check("normalize_mid 处理 int/None/空串",
          normalize_mid(up_mid) == up_mid and normalize_mid(None) is None
          and normalize_mid("") is None)
    check("归一化后置顶评论 mid 是 int", (pinned or {}).get("mid") == up_mid,
          repr((pinned or {}).get("mid")))

    # ---------- B3: 带货链接与商品卡片属性
    print("[B3] 链接来源与商品卡片投放属性")
    links = (pinned or {}).get("links") or []
    check("从 jump_url 提取到链接", len(links) >= 1, json.dumps(links, ensure_ascii=False)[:120])
    check("识别为商品卡片 kind=goods",
          any(l.get("kind") == "goods" for l in links))
    check("拿到 goods_item_id",
          any(l.get("goods_item_id") == 11460521 for l in links))
    goods = next((l for l in links if l.get("kind") == "goods"), {})
    signals = goods.get("ad_signals") or {}
    check("商品卡片带 is_ad_loc=true", signals.get("is_ad_loc") is True, json.dumps(signals))
    check("商品卡片带 creative_id", bool(signals.get("creative_id")), json.dumps(signals))
    check("链接标题非空", bool(goods.get("title")))

    print("[B3] 正文正则兜底")
    msg_links = extract_comment_links(
        {"message": "看这个 //mall.bilibili.com/x?a=1 和 https://example.com/b"})
    check("识别协议相对链接", any(l["url"].startswith("https://mall.bilibili.com")
                                  for l in msg_links), json.dumps(msg_links, ensure_ascii=False))
    check("mall 域名判为商品", any(l["kind"] == "goods" for l in msg_links))
    check("空 content 不报错", extract_comment_links({}) == [])

    # ---------- 端到端：判定为接广
    print("[E2E] judge_promo 判定")
    promo = judge_promo(pinned, up_mid)
    check("作者本人置顶 + 挂链接 -> is_promo", promo.get("is_promo") is True,
          json.dumps(promo.get("evidence"), ensure_ascii=False))
    check("is_author 为 True", promo.get("is_author") is True)
    check("带商品卡片标记", promo.get("has_goods_link") is True)
    check("commerce_signals 非空（B3 回归）", bool(promo.get("commerce_signals")),
          json.dumps(promo.get("commerce_signals")))

    print("[E2E] 负对照")
    other = judge_promo(pinned, up_mid + 1)
    check("非作者置顶 -> 不判接广", other.get("is_promo") is False)
    check("非作者时 is_author 为 False", other.get("is_author") is False)
    no_link = judge_promo({**pinned, "links": [], "message": "感谢支持"}, up_mid)
    check("作者置顶但无链接 -> 不判接广", no_link.get("is_promo") is False)
    none_pinned = judge_promo(None, up_mid)
    check("无置顶评论 -> 不判接广", none_pinned.get("is_promo") is False)
    check("无置顶时给出原因", "没有置顶评论" in (none_pinned.get("evidence") or [""])[0])

    print("[E2E] up_mid 传入字符串也应匹配（归一化）")
    as_str = judge_promo(pinned, str(up_mid))
    check("up_mid 传字符串仍判接广", as_str.get("is_promo") is True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

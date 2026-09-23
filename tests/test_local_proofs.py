"""离线自检（local-proof）：不联网、不需要登录。

覆盖：
  1. BV <-> AV 往返（含负对照）
  2. 输入解析（BV/av/链接/广告参数）
  3. 投流参数判定规则
  4. protobuf 弹幕解码（用 fixtures 里的真实字节）
  5. WBI fixed-input parity（用 live 页面自己生成的 w_rid 做 oracle）

用法：python tests/test_local_proofs.py
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from biliwb import ad as ad_mod  # noqa: E402
from biliwb import proto, utils, wbi  # noqa: E402

FIXTURES = ROOT / "js_reverse_cache" / "tasks" / "bili-workbench" / "fixtures"

PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  OK   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label} {detail}")


def test_bv_av() -> None:
    print("[1] BV <-> AV")
    for bvid, aid in [("BV1BHez6cEEm", 117303375104693), ("BV1X9eb6tEvy", 117296630598168)]:
        check(f"bv2av({bvid})", utils.bv2av(bvid) == aid, f"got {utils.bv2av(bvid)}")
        check(f"av2bv({aid})", utils.av2bv(aid) == bvid, f"got {utils.av2bv(aid)}")
    mutated = "BV1BHez6cEE" + "X"
    check("负对照：改末位的 BV 不应还原同一 aid",
          utils.bv2av(mutated) != 117303375104693)


def test_parse_video_ref() -> None:
    print("[2] 视频输入解析")
    ref = utils.parse_video_ref("BV1BHez6cEEm")
    check("纯 BV 号", ref["bvid"] == "BV1BHez6cEEm" and ref["aid"] == 117303375104693)
    ref = utils.parse_video_ref("av117303375104693")
    check("av 号", ref["bvid"] == "BV1BHez6cEEm")
    ref = utils.parse_video_ref(
        "https://www.bilibili.com/video/BV1X9eb6tEvy/?creative_id=3557007068"
        "&linked_creative_id=3557073625&caid=__CAID__&resource_id=__RESOURCEID__"
        "&source_id=5637&request_id=abc"
    )
    check("链接 + 广告参数", ref["bvid"] == "BV1X9eb6tEvy"
          and ref["ad"]["ad_params"].get("creative_id") == "3557007068")
    check("宏识别", set(ref["ad"]["macros"]) >= {"__CAID__", "__RESOURCEID__"})


def test_ad_rules() -> None:
    print("[3] 投流/接广判定")
    ad_url = ("https://www.bilibili.com/video/BV1X9eb6tEvy/?caid=__CAID__"
              "&resource_id=__RESOURCEID__&from_spmid=__FROMSPMID__&source_id=5637"
              "&creative_id=3557007068&request_id=1790064519651q10a88a112a128q5343")
    plain_url = ("https://www.bilibili.com/video/BV1BHez6cEEm/"
                 "?spm_id_from=333.1007.tianma.12-3-37.click&vd_source=c19f680b")
    r1 = ad_mod.judge_traffic(ad_url)
    r2 = ad_mod.judge_traffic(plain_url)
    check("广告位链接 -> is_ad", r1["is_ad"] is True, json.dumps(r1, ensure_ascii=False))
    check("普通推荐位链接 -> 非 ad", r2["is_ad"] is False, json.dumps(r2, ensure_ascii=False))
    check("广告位链接给出证据链", len(r1["evidence"]) >= 2)

    # 接广：置顶评论由作者本人发出且外挂链接
    promo = ad_mod.judge_promo(
        top_comment={"mid": 480959917, "message": "同款好物 https://m.tb.cn/h.xxxx"},
        up_mid=480959917,
    )
    check("作者置顶评论外挂链接 -> 接广", promo["is_promo"] is True,
          json.dumps(promo, ensure_ascii=False))
    other = ad_mod.judge_promo(
        top_comment={"mid": 12345, "message": "同款好物 https://m.tb.cn/h.xxxx"},
        up_mid=480959917,
    )
    check("非作者置顶评论外挂链接 -> 非接广", other["is_promo"] is False)
    no_link = ad_mod.judge_promo(
        top_comment={"mid": 480959917, "message": "感谢大家支持"}, up_mid=480959917)
    check("作者置顶但无链接 -> 非接广", no_link["is_promo"] is False)


def test_proto() -> None:
    print("[4] 弹幕 protobuf 解码")
    path = FIXTURES / "dm_seg_sample.bin"
    if not path.exists():
        check("fixtures/dm_seg_sample.bin 存在", False, str(path))
        return
    raw = path.read_bytes()
    top = proto.parse(raw)
    elems = top.get(1, [])
    check("能解出 elems", len(elems) > 0, f"n={len(elems)}")
    first = elems[0]
    msg = first.get("_msg") if isinstance(first, dict) else None
    check("elem 是嵌套消息", isinstance(msg, dict))
    if isinstance(msg, dict):
        content = proto.scalar(msg, 7)
        check("含弹幕正文(f7)", isinstance(content, str) and len(content) > 0, repr(content))
        check("含视频内时间(f2)", isinstance(proto.scalar(msg, 2), int))
        check("含发送时间(f8)", isinstance(proto.scalar(msg, 8), int))
        mid_hash = proto.scalar(msg, 6)
        check("含 midHash(f6)", isinstance(mid_hash, str) and len(mid_hash) == 8, repr(mid_hash))
        check("确认无 uid 字段（协议不下发）", "uid" not in {str(k) for k in msg})
    try:
        proto.parse(b"\xff\xff\xff\xff")
        malformed_ok = False
    except ValueError:
        malformed_ok = True
    check("负对照：非法字节流抛错而非产出 elems", malformed_ok)


def test_wbi_vectors() -> None:
    print("[5] WBI fixed-input parity（oracle = live 页面生成的 w_rid）")
    path = FIXTURES / "wbi_vectors.json"
    if not path.exists():
        check("fixtures/wbi_vectors.json 存在", False, str(path))
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    keys = data["candidate_keys"]["nav_wbi_img"]
    vectors = data["vectors"]
    good = 0
    for vec in vectors:
        ok, _ = wbi.verify_vector(vec["url"], keys["img_key"], keys["sub_key"])
        good += ok
    check(f"nav 下发的 key 全量复现 {good}/{len(vectors)}", good == len(vectors))
    stale = data["candidate_keys"]["page_default_wbi_key"]
    bad = sum(1 for vec in vectors
              if wbi.verify_vector(vec["url"], stale["img_key"], stale["sub_key"])[0])
    check("负对照：陈旧 defaultWbiKey 不应通过", bad == 0, f"matched={bad}")


def main() -> int:
    test_bv_av()
    test_parse_video_ref()
    test_ad_rules()
    test_proto()
    test_wbi_vectors()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())

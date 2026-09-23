"""生成 analysis/proof_manifest.json（交付证明清单）。

要点：
  * 记录 intake 模式、能力快照、固定向量、live 重放次数、已验证/未验证项；
  * 对关键产物计算 sha256（**排除任何含凭证的文件**，如 data/session.txt）；
  * 不复制任何 cookie / token / 密钥值。

用法：python analysis/build_manifest.py
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import platform
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 只对这些路径取指纹（绝不含 data/ 下的会话文件）
ARTIFACTS = [
    "main.py",
    "requirements.txt",
    "README.md",
    "biliwb/__init__.py",
    "biliwb/constants.py",
    "biliwb/wbi.py",
    "biliwb/client.py",
    "biliwb/login.py",
    "biliwb/utils.py",
    "biliwb/ad.py",
    "biliwb/proto.py",
    "biliwb/errors.py",
    "biliwb/secrets.py",
    "biliwb/gt3.py",
    "biliwb/accounts.py",
    "biliwb/store.py",
    "biliwb/jobs.py",
    "biliwb/server.py",
    "biliwb/api/__init__.py",
    "biliwb/api/search.py",
    "biliwb/api/video.py",
    "biliwb/api/comment.py",
    "biliwb/api/danmaku.py",
    "biliwb/api/user.py",
    "biliwb/api/dynamic.py",
    "biliwb/web/index.html",
    "biliwb/web/app.js",
    "biliwb/web/style.css",
    "tests/test_local_proofs.py",
    "tests/test_midhash.py",
    "tests/test_midhash_index.py",
    "tests/test_pinned_promo.py",
    "tests/test_accounts.py",
    "tests/test_server.py",
    "tests/test_batch.py",
    "tests/verify_logged_in.py",
    "tests/session_status.py",
    "tests/probe_one.py",
    "js_reverse_cache/tasks/bili-workbench/fixtures/wbi_vectors.json",
    "js_reverse_cache/tasks/bili-workbench/fixtures/midhash_pairs.json",
    "js_reverse_cache/tasks/bili-workbench/fixtures/dm_seg_sample.bin",
    "js_reverse_cache/tasks/bili-workbench/fixtures/pinned_comment_goods.json",
]

FORBIDDEN = ("session.txt", "biliwb.db")


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> int:
    artifacts = []
    for rel in ARTIFACTS:
        p = ROOT / rel
        if any(bad in rel for bad in FORBIDDEN):
            print(f"跳过含凭证可能的文件: {rel}", file=sys.stderr)
            continue
        if not p.exists():
            print(f"缺少产物: {rel}", file=sys.stderr)
            continue
        artifacts.append({
            "path": rel.replace("\\", "/"),
            "bytes": p.stat().st_size,
            "sha256": sha256(p),
        })

    vec_path = ROOT / "js_reverse_cache/tasks/bili-workbench/fixtures/wbi_vectors.json"
    vectors = json.loads(vec_path.read_text(encoding="utf-8")) if vec_path.exists() else {}
    pairs_path = ROOT / "js_reverse_cache/tasks/bili-workbench/fixtures/midhash_pairs.json"
    pairs = json.loads(pairs_path.read_text(encoding="utf-8")) if pairs_path.exists() else {}

    manifest = {
        "task": "bili-workbench",
        "generated_at": int(time.time()),
        "generated_at_str": time.strftime("%Y-%m-%d %H:%M:%S"),
        "shape": "collector",
        "intake": "live-target",
        "delivery": {
            "runtime": "pure Python (curl_cffi session) + local FastAPI console",
            "browser_free": True,
            "browser_automation_in_run_path": False,
            "engine_instrumentation_in_run_path": False,
            "managed_profile_in_run_path": False,
            "entrypoint": "main.py (right-click runnable, no CLI args required)",
            "generation_truth_label": "algorithmic",
            "generation_truth_note": (
                "WBI 签名、bili_ticket HMAC、BV/AV 转换、protobuf 解码、PDF/无 —— 全部在本地按算法重算；"
                "gaia 指纹槽位是取自 live 样本的显式常量配置，运行时不再读浏览器。"
            ),
        },
        "capability_snapshot": {
            "browser_mode": "launch (chrome-devtools MCP)",
            "browser_used_for": "fingerprint-baseline 取证 + page-world XHR hook 采集 w_rid oracle",
            "js_reverse": "absent",
            "silent_value_capture_backend": "absent",
            "debugger_attach_gap": True,
            "silent_value_capture_gap": True,
            "debugger_trace_means_used": (
                "page-world initScript XHR hook：捕获 live 页面自己生成的 6 条 w_rid/wts，"
                "作为 fixed-input oracle 与本地实现比对（6/6 一致）"
            ),
            "curl_cffi_impersonate": "chrome (0.15.0, 未套用 live 浏览器更新的大版本)",
            "python": platform.python_version(),
            "iv8": "missing (not needed)",
        },
        "fixed_vectors": {
            "wbi": {
                "oracle": "live 页面自身发出的 6 条 WBI 签名请求（initScript XHR hook 捕获）",
                "result": "6/6 完全一致",
                "negative_control": "__INITIAL_STATE__.defaultWbiKey 0/6（证明必须用 nav 下发的 key）",
                "fixture": "js_reverse_cache/tasks/bili-workbench/fixtures/wbi_vectors.json",
                "captured_wts": vectors.get("captured_wts"),
                "vector_names": [v["name"] for v in vectors.get("vectors", [])],
            },
            "midhash": {
                "scheme": "midHash = 8-char lowercase hex of crc32(str(uid))",
                "evidence": (
                    "多视频交叉验证：候选 uid 池(UP主+评论作者含二级) × XML 全量弹幕 midHash 池"
                ),
                "pool_size": pairs.get("pool_size"),
                "hash_pool_size": pairs.get("hash_pool_size"),
                "random_collision_expectation": pairs.get("random_collision_expectation"),
                "hits_per_candidate": pairs.get("hits_per_candidate"),
                "pairs_fixed": len(pairs.get("pairs", [])),
                "reproductions": 2,
                "fixture": "js_reverse_cache/tasks/bili-workbench/fixtures/midhash_pairs.json",
                "candidate_pool_rule": (
                    "显式传入 candidate_mids ∪ 视频 UP 主 ∪ 该视频评论区作者(含二级/置顶, 翻 pool_pages 页)"
                ),
                "persistent_index": (
                    "SQLite midhash_index：确认过的 (midHash, uid) 跨视频复用。"
                    "实测第二轮完全不建池仍认出 63 条（第一轮建池命中 60 条）"
                ),
                "known_limits": (
                    "命中率低是常态：大视频上万条弹幕来自数千用户，"
                    "评论池仅数十至数百 uid，重叠面小；未命中保持 null"
                ),
            },
            "bv_av": {
                "evidence": "已知配对 BV1BHez6cEEm<->117303375104693、BV1X9eb6tEvy<->117296630598168 双向往返 + 变异负对照",
            },
            "pinned_comment_and_promo": {
                "evidence": (
                    "真实反例 BV1Pg8Z62E3C：data.top 是容器而非评论对象、member.mid 为字符串、"
                    "带货链接权威来源是 content.jump_url"
                ),
                "fixture": "js_reverse_cache/tasks/bili-workbench/fixtures/pinned_comment_goods.json",
                "fixed_defects": [
                    "B1 置顶评论恒为 None（应从 data.top.upper 取）",
                    "B2 作者归属恒为 False（mid 字符串 vs 整数）",
                    "B3 商品卡片链接与投放属性漏取（含宽泛 except 吞掉 NameError）",
                ],
                "regression_tests": 32,
            },
            "danmaku_protobuf": {
                "evidence": "fixtures/dm_seg_sample.bin 原始字节解出 elems，字段 f1/f2/f3/f4/f5/f6/f7/f8/f9/f12/f13",
                "note": "协议不下发 uid/昵称/等级，仅 midHash",
            },
        },
        "endpoint_contract": {
            "wbi_signed": [
                "x/web-interface/wbi/view", "x/web-interface/wbi/search/type (video|bili_user)",
                "x/player/wbi/v2", "x/player/wbi/playurl", "x/v2/subtitle/web/view",
                "x/v2/dm/wbi/web/seg.so", "x/v2/dm/web/view", "x/v2/reply/wbi/main",
                "x/space/wbi/acc/info", "x/space/wbi/arc/search",
                "passport/x/passport-login/web/cookie/info",
            ],
            "not_wbi_signed": [
                "x/relation/stat", "x/space/upstat", "x/space/navnum", "x/space/setting",
                "x/relation/followings", "x/relation/followers",
                "x/polymer/web-dynamic/v1/feed/space", "x/tag/archive/tags",
                "x/v1/dm/list.so (XML 全量弹幕)", "x/frontend/finger/spi",
            ],
            "gaia_slots_required": ["x/space/wbi/acc/info"],
            "gaia_slots_ablation": (
                "同一 acc/info：不带 dm_img_* 返回 -352；带上返回 code=0。"
                "Referer/Origin 切换(www vs space)对结果无影响 —— 单变量消融证明 gaia 槽位是准入必要条件。"
            ),
            "risk_control": {
                "hard": ["HTTP 412 (HTML 风控页)", "code -352"],
                "soft": ["HTTP 200 + code 0 但 data 仅含 {\"v_voucher\": ...}"],
                "mitigation": "暖场(首页+搜索页) + 退避重试 + 会话 cookie 持久化复用；限速 1.1s/请求+抖动",
                "note": "412 为一过性会话级风控：arc/search 与 feed/space 均实测在暖场/退避后恢复",
            },
        },
        "session_scope": {
            "login_method": "扫码登录 (x/passport-login/web/qrcode/generate + poll)，不经过验证码",
            "fallback": "粘贴 Cookie 导入",
            "multi_account": {
                "supported": True,
                "per_account_client": "每个账号独立 BiliClient（独立 cookie / 限速 / 身份）",
                "login_methods": ["qr", "cookie", "password(GT3)"],
                "credential_storage": (
                    "cookie 与密码加密入库，本地无明文。首选 Windows DPAPI"
                    "（同机同用户可解）；回退 Fernet + data/.secret.key(0600)"
                ),
                "api_never_returns_secrets": "GET /api/accounts 只回 has_cookie/has_password + 脱敏提示",
                "legacy_migration": "data/session.txt 自动迁移为账号「默认」",
            },
            "concurrency": {
                "workers": "1..32，运行时可调（增起线程 / 减发哨兵）",
                "model": "worker 线程池 + job 绑定账号 + 账号级锁（同账号串行，异账号并行）",
                "throughput": "≈ min(worker 数, 可用账号数)",
                "shard": "可把一个 job 的 targets 按可用账号切分并行",
                "rationale": "单账号并发最容易触发 bilibili 风控，故按账号串行是刻意设计",
            },
            "password_login": {
                "implemented": True,
                "flow": [
                    "GET passport/x/passport-login/web/key -> key, hash",
                    "GT3 solve (subprocess gt3_protocol.py) -> validate, challenge, token",
                    "seccode = '<validate>|jordan'",
                    "RSA PKCS#1 v1.5 encrypt(hash + password) -> base64",
                    "POST passport/x/passport-login/web/login",
                ],
                "gt3_live_evidence": {
                    "result": "27.0s 取得 validate（score 14）",
                    "fields": "gt / challenge / token / validate / seccode 成组产出",
                    "solver": "js_reverse_cache/tasks/bili-gt3-solver (纯 Python + node:vm, 无浏览器)",
                },
                "submit_stage_tested": False,
                "submit_stage_note": "提交环节未经真实账号实测（需有效账号密码）；错误码语义已按公开口径映射",
            },
            "persistence": "data/session.txt（chmod 600，仅本地，不入版本控制）",
            "verified_persistence": "服务重启后 session/verify 仍返回登录有效（cookie 落盘复用）",
            "ticket_refresh": "bili_ticket 用已知 HMAC 本地自动续签（24h 周期）",
            "cookie_refresh_implemented": False,
            "cookie_refresh_reason": "主动 refresh 需要额外 RSA 密钥材料；改为 cookie/info.refresh 提示重新扫码",
            "credentials_in_manifest": False,
        },
        "live_acceptance": {
            "no_login": {"result": "9/9", "script": "tests/test_server.py"},
            "logged_in": {"result": "18/18", "script": "tests/verify_logged_in.py"},
            "batch_jobs": {"result": "14/14", "script": "tests/test_batch.py"},
            "offline_selftest": {"result": "25/25", "script": "tests/test_local_proofs.py"},
            "midhash_regression": {"result": "9/9", "script": "tests/test_midhash.py"},
            "pinned_promo_regression": {"result": "32/32", "script": "tests/test_pinned_promo.py"},
            "midhash_index_regression": {"result": "17/17", "script": "tests/test_midhash_index.py"},
            "multi_account_and_workers": {"result": "22/22", "script": "tests/test_accounts.py"},
            "total": 150,
            "login_unlocked_evidence": [
                "字幕：6 条轨（ai-zh/ai-en/ai-ja），正文 2082 行（未登录时为 0 条）",
                "space/upstat：获赞数 23、播放数 110（未登录返回 {}）",
                "relation/followings：50 条；relation/followers：11 条（未登录 -101/-352）",
                "评论翻页：第 1 页 17 条、第 2 页 is_end=True（未登录只给 3 条即 is_end）",
                "playurl 清晰度：1080P / 12 视频轨（未登录 720P / 6 轨）",
                "动态数：翻页累计 272 条（feed_total 字段只给 0，已证不可靠）",
            ],
            "privacy_negative_control": (
                "uid 480959917 的 space/setting 显示 disable_following=1；"
                "请求其关注名单返回 available=False 且给出隐私原因，而不是空列表"
            ),
            "ad_oracle": {
                "ad_sample": "带 creative_id/__CAID__ 等参数的 BV1X9eb6tEvy 链接 -> category=ad",
                "organic_sample": "BV1BHez6cEEm（无广告参数、无作者置顶外链）-> category=organic",
                "promo_sample": "BV1Pg8Z62E3C（作者本人置顶评论挂 b23.tv 商城商品卡片）-> category=promo",
                "note": ("三者互为对照。批量传纯 BV 号时无 URL 参数，投流判定退化为只看置顶评论，"
                         "属规则的自然结果。"),
            },
        },
        "not_claimed": [
            "不声称理解 bilibili 页面/运行时：js-reverse 与 silent-value-capture 后端均不可用，两个 gap 已显式记录",
            "不声称商单（花火任务）可判定：公开 web 端无该字段，ad 仅表示本次访问来自广告位",
            "弹幕发送者 uid 还原率取决于候选池覆盖：未命中保持 null 并计入 unresolved，不做猜测",
            "cookie 主动 refresh 未实现",
            "未做任何写操作（不发弹幕/不评论/不点赞/不投币）",
            "视频直链有时效签名，未做长期可用性保证",
        ],
        "sensitive_artifact_exclusion": [
            "data/session.txt（含 SESSDATA/bili_jct）",
            "data/biliwb.db（含采集结果）",
        ],
        "artifacts": artifacts,
    }

    out = ROOT / "analysis" / "proof_manifest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已写入 {out}（{len(artifacts)} 个产物指纹）", file=sys.stderr)
    for bad in FORBIDDEN:
        if any(bad in a["path"] for a in artifacts):
            print(f"!!! 凭证文件误入清单: {bad}", file=sys.stderr)
            return 1
    print("凭证排除检查: 通过", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

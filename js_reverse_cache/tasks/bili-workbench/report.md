# bilibili 本地采集工作台 —— 协议取证与验收报告

- **任务**：`bili-workbench`
- **交付形态**：`collector`（浏览器无关的纯 Python 采集器 + 本地控制台）
- **intake**：`live-target`
- **gate family**：`signer-gated`（主），次标签 `transport-gated` / `decode-gated` / `session-gated`
- **一句话结论**：bilibili 的业务数据接口**没有响应加密**；真正的门槛是**请求侧 WBI 签名 + gaia 准入 + 会话登录态**。这三项已全部在本地纯 Python 复现并 live 验收通过。

---

## 1. Startup Gate 与能力快照

| 项 | 值 |
|---|---|
| browser mode | `launch`（chrome-devtools MCP，29 个工具） |
| browser 用途 | 仅 `fingerprint-baseline` 取证 + `initScript` page-world 采集签名 oracle |
| `js-reverse` | **absent** → `debugger_attach_gap = true` |
| `silent-value-capture` 后端 | **absent** → `silent_value_capture_gap = true` |
| `debugger-trace` 采用的手段 | page-world `initScript` XHR hook（见 §2.2） |
| curl impersonate | `chrome`（curl_cffi 0.15.0，**未套用** live 浏览器更新的大版本） |
| python | 3.13.5 |
| iv8 | missing（本任务不需要） |
| 账号/会话 | 用户本人扫码登录（uid 494757969），仅只读采集 |

**必须明确的限制**：`js-reverse` 与 silent-value 后端都不可用，因此本报告**不声称"理解页面运行时"**。
两个 gap 已显式记录；`debugger-trace` 角色用 page-world 关联捕获补齐（§2.2），并非零证据。

---

## 2. 证据面

### 2.1 fingerprint-baseline（chrome-devtools，未插桩的干净基线）

对参照样本 **BV1X9eb6tEvy（带广告参数）** 与 **BV1BHez6cEEm（普通）** 取基线：

- 捕获真实业务请求形状：`x/player/wbi/playurl`、`x/player/wbi/v2`、`x/v2/dm/web/view`、
  `x/v2/dm/wbi/web/seg.so`、`x/v2/subtitle/web/view`、`x/v2/reply/wbi/main`、
  `x/space/wbi/arc/search`、`x/space/wbi/acc/info`、`x/relation/stat`、`x/space/upstat`、
  `x/space/navnum`、`x/space/setting`、`x/polymer/web-dynamic/v1/feed/space`、
  `bapis/.../GenWebTicket`、`x/frontend/finger/spi`。
- **广告字段取证（关键否定结论）**：两样本的 `window.__INITIAL_STATE__.videoData` 键集合完全相同，
  **没有任何 per-video 广告字段**；`adData`（槽位 2624/2625/3038/4330）两样本值一致，
  `is_ad_loc:"false"`、`cm_mark:"0"`、`business_mark:"null"`、`adver_name:""`。
  页面正文也搜不到「广告 / 商业推广」标签。
  → 与参考文档结论一致：**公开 web 端不存在"是不是商单"的字段**。
- **会话事实**：`x/player/wbi/v2` 返回 `login_mid:0`、`need_login_subtitle:true`、`subtitles:[]`
  —— 基线浏览器未登录，由此确认登录是字幕等字段的硬前置。

### 2.2 page-world 关联捕获（debugger-trace 的替代手段）

在 `navigate_page(initScript=...)` 于 document-start 挂钩 `XMLHttpRequest.prototype.open/send`，
捕获**页面自己生成**的 WBI 签名请求：

| # | 端点 | 捕获到的 `w_rid` | `wts` |
|---|---|---|---|
| 1 | `x/player/wbi/v2` | `c67299d3…` | 1790068866 |
| 2 | `x/v2/dm/web/view` | `8c7be687…` | 1790068866 |
| 3 | `x/v2/subtitle/web/view` | `71dbc7ba…` | 1790068866 |
| 4 | `x/v2/dm/wbi/web/seg.so` | `d261c99f…` | 1790068867 |
| 5 | `x/click-interface/web/heartbeat` | `efe0beed…` | 1790068867 |
| 6 | `x/click-interface/click/web/h5` | `2c09dfe7…` | 1790068867 |

这 6 条成为 §4 的 **fixed-input oracle**。同时从同一会话取到两组候选密钥：
`__INITIAL_STATE__.defaultWbiKey` 与 `GET x/web-interface/nav → data.wbi_img`。

### 2.3 离线证据

- 弹幕二进制原始字节（`fixtures/dm_seg_sample.bin`，635 B）本地解码。
- 静态结论：live 页面的 webpack 已模块联邦化，`webpackChunk*` 全局只剩日志/弹幕播放器包，
  **无法**用页面内模块做 WBI 的静态交叉验证 —— 因此改用更强的**服务端 oracle**。

---

## 3. 协议发现

### 3.1 WBI 签名（signer-gated 主体）

```
mixin_key = (img_key + sub_key)[MIXIN_KEY_ENC_TAB][:32]
query     = 除 w_rid/wts 外参数按 key 升序，"!'()*" 从值中剔除后 percent-encode
w_rid     = md5(query + mixin_key)          # wts 是参与排序的普通参数
```

**关键发现（违反直觉，已用负对照证明）**：必须使用 `GET /x/web-interface/nav` 下发的
`data.wbi_img`；`__INITIAL_STATE__.defaultWbiKey` 是**陈旧预置值，用它签名 0/6 匹配**。

### 3.2 gaia 准入槽位（transport/admission-gated）

`x/space/wbi/acc/info` 的单变量消融（一次只动一个自变量）：

| 变体 | 结果 |
|---|---|
| www Referer（基线） | `-352` 风控 |
| space Referer + Origin | `-352` 风控 |
| **space Referer + `dm_img_*` 槽位** | **`code=0`** |
| **www Referer + `dm_img_*` 槽位** | **`code=0`** |

→ **决定性变量是 `dm_img_list` / `dm_img_str` / `dm_cover_img_str` / `dm_img_inter`，
与 Referer/Origin 无关。** 这些值取自 live 样本，作为 `biliwb/constants.py` 里的
**显式配置输入**，运行时不读浏览器（符合 delivery gate 第 8 条）。

### 3.3 两类风控（均已显式处理）

| 类型 | 形态 | 处理 |
|---|---|---|
| 硬风控 | `HTTP 412`（HTML 风控页）/ `code -352` | 退避重试；失败则结构化报错 |
| **软风控** | `HTTP 200 + code 0`，但 `data` **只有** `{"v_voucher": ...}` | 识别为"200 填充值惩罚"并重试 |

软风控的触发条件是**会话新鲜度**而非内容：全新 `buvid` 会话直打搜索接口会命中；
暖场（首页 + 搜索页）后退避重试即恢复完整 `result=30`。

**一过性 412 实证**：`x/space/wbi/arc/search` 与新会话首次 `feed/space` 都曾 412，
暖场/退避后同一请求成功 —— 归类为 `egress-environment` 级波动，不是实现失败。

### 3.4 弹幕协议（decode-gated）

`x/v2/dm/wbi/web/seg.so` 返回 `application/octet-stream` 的 protobuf（**不是加密**）。
实测 `DanmakuElem` 字段：

```
f1 id | f2 progress(视频内毫秒) | f3 mode | f4 fontsize | f5 color
f6 midHash | f7 content | f8 ctime(发送时间) | f9 weight | f12 idStr | f13 attr
```

**分段语义（纠正了一个常见误解）**：

- 权威段数来自 `x/v2/dm/web/view` 的 `DmSegConfig = {page_size: 360000ms, total: N}`，
  **不是** `ceil(duration/360)` 猜出来的；实测 854s 视频 `total=3`（与猜测一致），
  但 1343s 视频 `total=1`（与猜测不符）。
- `segment_index` 从 1 开始；**不存在的段返回 404**（不是空数组），必须视为空段。
- 段内 `ps`/`pe` 是毫秒窗口，`pe` 不得超过 `page_size`（超出返回 404）。

**互补路径**：`x/v1/dm/list.so`（XML）的 `p` 属性为
`progress(秒),mode,fontsize,color,ctime,pool,midHash,rowID,weight`。
实测对中小弹幕视频返回**全量**且与 `stat.danmaku` 完全一致（286/286、35/35），
而 seg.so 对同一视频只给 103/12 条 —— 因此默认**两条路径都取并合并去重**。

### 3.5 midHash（弹幕发送者 uid 还原）

协议**不下发** uid / 昵称 / 等级，只有 `midHash`。用跨视频交叉验证确定算法：

```
midHash = crc32(str(uid)) 的 8 位小写 hex
```

**取证方法**：对 15 个视频分别收集
（候选 uid 池 = UP 主 mid + 评论区含二级作者 mid）×（弹幕 midHash 池 = XML 全量）。

| 候选算法 | 命中数 |
|---|---|
| **`crc32(str(uid))`** | **47** |
| `crc32(str(crc32(uid))+"DU8tF3z6")`（双重加盐，最初的错误假设） | 0 |
| `crc32(str(uid)+盐)` / `crc32(盐+str(uid))` / `crc32(str(crc32(uid)))` | 0 |
| `md5(str(uid))[:8]` / `crc32(uid 的 8 字节整数)` | 0 |

池规模 415 uid × 18084 midHash，**随机碰撞期望仅 1.75e-03**，独立复现 2 次
（19 命中 / 47 命中），其余候选全部 0 命中 → 规则唯一确定。

**候选池的构造与命中率**：池 = 显式传入的 uid 名单 ∪ 视频 UP 主 ∪ 该视频评论区作者
（含二级、置顶，翻 `pool_pages` 页）。实测命中率低是常态：

| 视频 | 弹幕数 | 池 | 命中 |
|---|---|---|---|
| BV1woez6TECm | 3776 | 28 | 58 |
| BV1Dt4y1S7tG | 1830 | 48 | 2 |
| BV1pB4y1x7wC | 1257 | 22 | 1 |
| BV1BHez6cEEm | 35 | 12 | 0 |
| BV1sT4y127SN | 16530 | 46 | 0 |

**持久化 midHash 字典**：由于 `midHash` 只是 uid 的函数、与视频无关，确认过的
`(midHash, uid)` 可跨视频复用。落地为 SQLite 表 `midhash_index`（命中即入库，
enrich 到的昵称/等级回写）。实测 4 个视频：第一轮建池命中 60 条；**第二轮完全不建池**
（池里只剩 1 个 UP 主）仍认出 **63 条**，全部来自字典；其中某视频第一轮 0 命中、
第二轮字典认出 3 条。即"采集越多、还原率越高"。回归测试 `tests/test_midhash_index.py`（17 项）。

**交付后修复（第四个缺陷）**：`_pool_from_comments` 曾把数字 aid 直接传给
`parse_video_ref()`，解析抛错被 `except` 吞掉，导致**候选池恒为空、uid 还原从未生效**。
修复为 `av2bv(aid)` 后再交给评论模块，并把 UP 主与置顶评论作者一并入池。

### 3.6 广告判定（按需求口径）

```
有 ad 字段特征 ──────────────────────────────→ 投流 ad（与置顶评论无关）
无 ad 字段特征 + 作者本人置顶评论外挂链接 ────→ 接广 promo
两者都没有 ──────────────────────────────────→ organic
```

ad 字段特征的信度分层与"必须排除"的字段见 `README.md`。
live 负对照：带 `creative_id`/`__CAID__` 等参数的链接 → `ad`；普通 BV → `organic`。
`space/setting` 的 `privacy.disable_following` / `disable_show_fans` 用于关系链隐私提示。

**交付后修复（由用户提供的真实反例驱动）**：用户指出 `BV1Pg8Z62E3C` 明明挂了带货链接却判为
`organic`。定位到三个独立缺陷，全部修复并固化为 `tests/test_pinned_promo.py`（32 项）：

| 编号 | 缺陷 | 根因 | 修复 |
|---|---|---|---|
| B1 | 置顶评论恒为 `None` | `data.top` 是容器 `{admin, upper, vote}`，不是评论对象；对其取 `rpid` 永远为空 | 改从 **`data.top.upper`** / `top.admin` 取，`top_replies` 兜底；抽出纯函数 `extract_pinned()` |
| B2 | "置顶评论是否作者本人"恒为 False | `member.mid` 是**字符串** `'542316830'`，`view.owner.mid` 是**整数** `542316830` | 统一 `normalize_mid()` 归一化后比较 |
| B3 | 带货链接识别不到 / 商品卡片属性为空 | ① 商品卡片在正文里可能只有文字，权威来源是 `content.jump_url`；② `goods_prefetched_cache` 解析失败被**宽泛 `except Exception` 吞掉了 `NameError`**（`utils.py` 漏 `import json`） | 从 `jump_url` 取链接并识别 `goods_item_id`；补 import 并把 except 收窄为 `(ValueError, TypeError)` |

修复后同一视频：`category=promo`，`pinned_source=top.upper`，`pinned_is_author=True`，
`goods_item_id=11460521`，且商品卡片的 `is_ad_loc=true` / `creative_id=1196650964874997760`
被正确提取（此前为空）。

**一个口径澄清**：商品卡片自带的 `is_ad_loc` / `creative_id` 属于**评论商品卡片**的广告属性，
**不是视频自身的 ad 字段特征**，因此按需求规则仍计入「接广」而非「投流」；
该信号以 `ad_verdict.commerce_signals` 形式单独暴露，不改变分类。

---

## 4. 固定向量与离线证明

**WBI fixed-input parity**（oracle = live 页面自己生成的 6 条 `w_rid`）：

```
nav 下发的 key     : 6/6 完全一致   ← PASS
defaultWbiKey      : 0/6            ← 负对照成立（证明密钥来源唯一）
```

**离线自检套件**（不联网、不需要登录）：

| 套件 | 结果 |
|---|---|
| `tests/test_local_proofs.py` | **25/25** |
| `tests/test_midhash.py` | **9/9**（47 个真实配对 + 6 个负对照） |

---

## 5. Live 验收

| 场景 | 脚本 | 结果 |
|---|---|---|
| 未登录 | `tests/test_server.py` | **9/9** |
| **已登录** | `tests/verify_logged_in.py` | **16/16** |
| 批量任务 | `tests/test_batch.py` | **14/14** |
| 会话落盘复用 | `tests/session_status.py` | 服务重启后仍返回登录有效 |

**登录解锁的实测差异**（同一批请求，登录前后对比）：

| 字段/能力 | 未登录 | 已登录 |
|---|---|---|
| 字幕 | 0 条 | **6 条轨（ai-zh/ai-en/ai-ja），正文 2082 行** |
| 获赞数 / 播放数 | `null` / `null` | **23 / 110** |
| 关注名单 / 粉丝名单 | `-101` / `-352` | **50 条 / 11 条** |
| 评论首页 | 3 条 | **17 条**（第 2 页 `is_end=True`） |
| 播放清晰度 | 720P / 6 视频轨 | **1080P / 12 视频轨** |
| 动态数 | `total` 恒 0 | **翻页累计 272 条** |

**隐私负对照**：uid 480959917 的 `space/setting` 显示 `disable_following=1`；
请求其关注名单得到 `available=False` + 明确隐私原因，而不是空列表。

**弹幕覆盖**：BV1BHez6cEEm `35/35`、BV1X9eb6tEvy `301/301`，`coverage.complete=True`。

---

## 6. 未证明项与盲区（如实标注）

1. **无 js-reverse / silent-value 后端** → `debugger_attach_gap` 与 `silent_value_capture_gap` 持续存在；
   不声称理解页面运行时。`debugger-trace` 由 page-world oracle 补齐（§2.2）。
2. **商单（花火任务）不可判定** —— 公开 web 端无字段；`ad` 只表示"本次访问来自广告位"。
3. **弹幕发送者 uid 还原率受候选池覆盖限制** —— 未命中保持 `null` 并计入 `unresolved`。
4. **cookie 主动 refresh 未实现**（需额外 RSA 密钥材料）；改用 `cookie/info.refresh` 提示重新扫码。
5. **`feed/space` 的 `total` 字段不可靠**（有 12 条 items 却返回 `"0"`）→ 需要准确值时用翻页累计。
6. **视频直链带时效签名**，未做长期可用性保证。
7. `arc/search`、`feed/space` 存在**一过性 412**（暖场/退避后恢复），属 `egress-environment` 级波动。
8. 全程**只读**：不发弹幕、不评论、不点赞、不投币。

---

## 7. 产物清单

| 路径 | 说明 |
|---|---|
| `main.py` | 交付入口（右键运行，无需参数） |
| `biliwb/` | 采集核心：WBI / 会话 / 客户端 / 广告判定 / protobuf / 8 项 API / SQLite / 批量队列 / FastAPI |
| `biliwb/web/` | 本地控制台前端（原生 JS，无 CDN） |
| `tests/` | 离线自检 + 端到端自检 + 登录态专项 + 批量验证 |
| `analysis/proof_manifest.json` | 交付证明清单（35 个产物指纹，凭证排除已校验） |
| `js_reverse_cache/tasks/bili-workbench/fixtures/` | WBI 固定向量、midHash 真实配对、弹幕原始字节 |
| `js_reverse_cache/tasks/bili-workbench/probe_*.py` | 各阶段取证脚本（准入消融、分段澄清、midHash 证明等） |

**浏览器无关性**：最终运行路径为纯 Python（curl_cffi 会话）——无浏览器自动化、无 CDP 页面驱动、
无浏览器 profile、无采集后端、无引擎插桩。浏览器仅用于 §2 的取证。

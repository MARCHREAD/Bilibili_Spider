# 从 0 到通过：bilibili 登录极验（Geetest GT3 文字点选）纯算法过验证 · 全流程学习笔记

> 这份文档按**我实际走过的顺序**写的
> 每个结论都注明「怎么判断出来的」，从「症状 → 原因 → 修正方法」流程来写。
> 目标读者：想自己复现一遍的人。

---

## 0. 结论速览

| 项 | 内容 |
|---|---|
| 目标 | `https://passport.bilibili.com/login` 的登录验证码 |
| 发现 | **Geetest GT3**，且该 gt 派发的是**文字点选**（不是滑块） |
| 交付 | `python main.py --rounds 2` → 免浏览器，2/2 拿到 `validate` |
| 关键难点 | ① 判定形态 ② 免浏览器跑原始 JS ③ 反解答案 `a` 的编码 ④ 识别字形 |
| 每轮成本 | 约 11 个 HTTP 请求、30~40 秒 |

免浏览器成功记录（`/ajax.php` 原始判决）：

| 入口 | validate | score |
|---|---|---|
| `main.py` | `8853bdefeda3badc3bdded8e0c45c704` | 14 |
| `main.py` | `e155b58f2ffdf6cd3d4d147889e46596` | 14 |
| `gt3_protocol.py` | `ff8eecc860a1bb06e86c0cb8c12eb330` | 14 |
| `gt3_protocol.py` | `60a14f3a4ccce8158149228e9b45d54d` | 14 |
| `gt3_protocol.py` | `564319ddab11d6d5930f137a7d503273` | 14 |

真机（浏览器）复核：`8f2ac79d6fb948e21cccee175f3753ff`（提示词「动丽」）、
`8acab457191d1b47b44d2fd33c9c0eca`（提示词「瓣藤」）。

---

## 1. 第 0 步：怎么判断"这个登录验证用的是 GT"

这一步的目标只有一个：**用三条互相独立的证据确认"是不是 Geetest"，以及"是第几代"**。不要靠肉眼看到"有个拼图"就下结论。

### 1.1 三条互相印证的判据（按可靠性排序）

**判据 A：业务侧自己的取参接口（最可靠，可直接当代码入口）**

极验是第三方服务，"业务服务器"必须先向极验申请参数再交给前端。bilibili 的这个接口是：

```
GET https://passport.bilibili.com/x/passport-login/captcha?source=main-fe
```

实测返回（本次原始抓取）：

```json
{"code": 0, "message": "OK", "ttl": 1,
 "data": {"type": "geetest",
          "token": "1497c9784b5e438abb576d7ee8ab6df9",
          "geetest": {"challenge": "d530669bf21e89dc506251d862f063b8",
                      "gt": "ac597a4506fee079629df5d8b66dd4fe"},
          "tencent": {"appid": ""}}}
```

怎么看：
* `data.type == "geetest"` → 这次挑战用的是极验（若为 `tencent` 就是腾讯验证码，直接换方向）
* `data.geetest.gt` → 站点在极验后台申请的 id（bilibili 这个是 `ac597a4506fee079629df5d8b66dd4fe`），**后面所有请求都要带它**
* `data.geetest.challenge` → 本轮挑战串，**一轮一变**，是"新鲜度"的核心
* `data.token` → 业务侧回执用，与极验无关

> 这一步顺手就把"每次要现取 challenge"这件事解决了：**验收必须每轮重新调这个接口**，复用旧 challenge 直接 `error_51`。

**判据 B：网络面板出现极验域名**

* `api.geetest.com/gettype.php`、`/get.php`、`/ajax.php`
* `static.geetest.com/static/js/fullpage.9.2.0-guwyxh.js`（主控）
* `monitor.geetest.com/monitor/send`（错误上报：**它出现就等于"你刚把 SDK 弄报错了"**）

**判据 C：DOM 与全局对象**

* class 前缀 `geetest_`：`geetest_holder` / `geetest_panel` / `geetest_item_wrap` / `geetest_commit`
* 全局函数 `window.initGeetest`

### 1.2 判断是第几代（GT3 还是 GT4）

这一步非常重要，因为**两代的算法完全不同**，走错方向会白干很久。

| 特征 | **GT3**（本次） | GT4 |
|---|---|---|
| 业务取参给的东西 | `gt` + `challenge` | `captcha_id` |
| 首个入口请求 | `api.geetest.com/gettype.php?gt=..&callback=..` | `gcaptcha4.geetest.com/load?captcha_id=..` |
| 主流程 | `get.php?gt&challenge&w=..` | `/load`、`/verify` |
| 产品脚本 | `fullpage.9.2.0-guwyxh.js`、`slide.7.9.3.js`、`click.3.1.2.js` | `gcaptcha4.js` |
| 回调给业务的字段 | `geetest_challenge` / `geetest_validate` / `geetest_seccode` | `lot_number` / `captcha_output` / `pass_token` / `gen_time` |
| 提交参数 | 一个 `w`（自定义 base64 密文 + `.` + 256 hex RSA） | 多个 JSON 字段 |
| 校验请求 | `ajax.php`（**jsonp**，返回 `{"result":"..."}`） | `/verify`（POST JSON） |

本次判定依据：出现 `gettype.php` + `get.php?...&w=` + `fullpage.9.2.0-guwyxh.js`，且业务接口给的是 `gt`+`challenge` → **GT3**。

> 顺带记住 GT3 的 jsonp 形态：所有 `api.geetest.com` 的响应都是 `geetest_<时间戳>({...})`，
> 也就是说**你的运行环境必须能被回调到同名全局函数**（这决定了后面 VM 里必须实现 jsonp）。

### 1.3 判断"是哪种验证形态"（最容易想当然的一步）

**核心认知：初始 `w` 不决定形态。形态由一次"预检/雷达"决定。**

实测的完整请求序列（真机与本地 VM 两边逐条一致）：

| # | 请求 | 关键参数 | 作用 / 返回值 |
|---|---|---|---|
| 1 | `gettype.php` | `gt`, `callback` | 探测；`after-response` 里能看到 core 还没建（`core:false`） |
| 2 | `fullpage.9.2.0-guwyxh.js` | — | 主控脚本（304 KB） |
| 3 | `get.php` | `gt, challenge, lang=zh-cn, pt=0, client_type=web, w=<1452 字符>` | 返回 `theme/static_servers/c/s/...`；**此时还不知道形态** |
| 4 | `ajax.php` | 同上，`w=<704 字符>` | **返回 `{"result":"click"}`** ← 这就是形态判定 |
| 5 | `click.3.1.2.js` | — | 按第 4 步的结论加载对应产品脚本（不是 `slide.7.9.3.js`） |
| 6 | `get.php?is_next=true&type=click` | `api_server/protocol/offline/isPC/autoReset/width/product...` | 返回**轮次载荷 + 轮次图** |
| 7 | `gct.<md5>.js` | — | 指纹脚本（请求参数里的 `gct` 由它算出） |
| 8 | `style_https.1.5.8.css` / `silver 1.5.4.css` | — | 主题样式（VM 里**必须触发 link 的 load 事件**，见 §7） |
| 9 | `ajax.php` | `w=<密文 + "." + 256 hex>` | **最终提交**，返回 `{"result":"success","validate":"..."}` |

第 6 步的轮次载荷（原始）：

```json
{"theme":"silver","spec":"1*1","sign":"","pic":"/captcha_v3/batch/v3/154063/2026-09-21T20/word/....jpg",
 "pic_type":"word","num":0,"c":[12,58,98,36,43,95,62,15,12],"s":"7028336a", ...}
```

形态对照（`pic_type` 是关键字段）：

| `result` | `pic_type` | 产品脚本 | 交互形态 |
|---|---|---|---|
| `slide` | — | `slide.7.9.3.js` | 滑块拼图 |
| `click` | `word` | `click.3.1.2.js` | **文字点选**（按提示词顺序点字） |
| `click` | `nine` | `click.3.1.2.js` | 九宫格点选 |
| `click` | `phrase` / `icon` / `space` | `click.3.1.2.js` | 短语 / 图标 / 空格点选 |

> **踩坑**：这个任务最初的前提是"滑块：52 片还原 + 算距离"，但我用真机一测，第 4 步返回的是
> `{"result":"click"}`，第 6 步 `pic_type:"word"` —— 是**文字点选**，滑块那条路在这个 gt 上根本不存在。
> **教训：先实测形态，再设计算法。** 我把这个结论写进报告后才继续，否则后面所有工作都会白做。

---

## 2. 协议全链路：每一步在做什么

### 2.1 `w` 有三种，长度和结构都不一样

| 阶段 | 长度（我方/真机） | 结构 | 谁生成 |
|---|---|---|---|
| 初始 `get.php` 的 `w` | 1452 / 1452 | 无 `.` 分段 | fullpage 主控（VM 内成功复现） |
| 预检 `ajax.php` 的 `w` | 704 / 1260 | 真机无 `.` 分段 | 雷达 |
| 最终 `ajax.php` 的 `w` | 664 / 1260 | **密文 + `.` + 256 hex** | 点选产品（VM 内由 SDK 自己生成） |

最终 `w` 的形状拆解：

```
w = 自定义base64( AES( JSON.stringify(o), key ) )  +  "."  +  256 hex (RSA-1024 包裹的 key)
```

* 密文长度随明文增长：真机明文约 750 字节 → 1003 字符密文；我方明文约 300 字节 → 407 字符
* `.` 后面**必定是 256 个 hex**（RSA-1024），这是"真的走到了最终提交"的判据之一

### 2.2 明文只有 6 个业务字段（+站点附加）

```json
{"lang":"zh-cn","passtime":5595,"a":"2476_4970,7499_2491",
 "pic":"/captcha_v3/.../word/....jpg","tt":"<200+ 字符>",
 "ep":{"ca":[...],"v":"3.1.2","$_FG":false,"me":true,"tm":{...}},
 "h9s9":"1816378497","rp":"e0360a6c4d78dca1fea44da35b5a385b"}
```

* `a` = 答案（点选坐标，见 §4）
* `tt` = 用本轮的 `s`（hex）往一个长串里按 `c[0]/c[2]/c[4]` 算出的位置插字符，即 `len(tt) = len(源串) + len(s)/2`
* `ep` = 环境/行为对象：`ca` 是点击轨迹、`tm` 是 20 个时间戳、`me` 是"检测到鼠标事件"
* `h9s9` / `rp` 是站点级附加字段（不同站点会有别的键）

### 2.3 用 `ajax.php` 的返回值判断"我走到哪一步了"

| 返回值 | 含义 | 我该做什么 |
|---|---|---|
| `{"result":"click"}` | 预检通过，形态=点选 | 继续点选流程 |
| `{"result":"success","validate":"..."}` | ✅ 通过 | 收工，记录 validate |
| `{"result":"fail"}` | 位置或顺序不对 | 改求解器 |
| `{"error":"runtime error","error_code":"error_00"}` | 报文结构/类型不对（早期我把 `a` 当数组传就是这么报的） | 改答案编码 |
| `error_12`（尝试过多） | 失败次数太多被限流 | 降低重试、别乱点 |
| `error_51`（proof status is 1） | 该轮已被消费，重复提交 | 拿到 validate 立刻停 |

---

## 3. 免浏览器运行环境（整个工程的核心）

### 3.1 设计思想

> **Python 拥有全部 HTTP，Node 只负责跑原始 JS。**

理由：极验对 TLS/HTTP 指纹敏感，用 Python 统一发请求好控制、好抓包；
而 JS 逻辑（含加密、RSA、自定义 base64）一行都别自己重写，直接跑它的原码。

结构：

```
gt3_protocol.py          取新 challenge；应答 SDK 的每一个 HTTP 请求；解析判决
  └── env/run.js         node:vm 沙箱 + env-patch（假 window/navigator/location/document/DOM/CSS）
        ├── fullpage.9.2.0-guwyxh.js   原始资源（仅最小补丁导出内部对象）
        └── click.3.1.2.js             同上
```

双方通过 **JSONL（一行一个 JSON）** 在 stdin/stdout 上对话：Node 说"我要请求 X"，
Python 抓完把响应体喂回去；Node 说"我算出了 w"，Python 记录。

### 3.2 最小补丁：把内部对象"导出来"

点选的**提交方法**（属性名 `$_BJJQ`）挂在一个**内部 widget 对象**上，从 `inst`/`core`/`window`
沿原型链走 4 层都摸不到。所以只能给资源文件打**最小补丁**：

| 脚本 | 产物 | 插入了什么 | 体积变化 |
|---|---|---|---|
| `patch_core.py` | `cache/fullpage.patched-core.js` | `globalThis.__gt3Core = …` | +21 B |
| `patch_click_widget.py` | `cache/click.patched-widget.js` | widget 方法入口 `globalThis.__gt3Widget=this`（19 处）、加密前 `globalThis.__gt3Plain=o` | +575 B |

规矩：
* **只插入语句，绝不改原逻辑**；原始文件保持不动
* raw 与 patched 都记 `sha256` 清单（`*_patch_manifest.json`），能证明"跑的是同版本原码"
* 补丁产物**必须 `node --check` 校验语法**（我在这里踩过大坑，见 §7）

### 3.3 环境补丁要"够真"，否则产品根本不渲染

最小可用集合（每一条都对应一个失败现象，详见 §7）：

1. `navigator`（`userAgent`、`platform`、`plugins`、`languages`、`webdriver`）
2. `location` / `document`（`documentElement`、`body`、`head`、`createElement`、`getElementsByTagName`）
3. **CSS 特征探测**：`'transition' in documentElement.style` 必须为真（否则被判 IE）
4. `addEventListener` / **事件冒泡** / `MouseEvent` / `requestAnimationFrame`
5. `<link rel=stylesheet>` 的 **load 事件必须触发**（否则 `onReady`/`verify` 永不到来）
6. **虚拟时钟**：延迟定时器不能在轮次开始前被全部抽干

### 3.4 怎么"让 SDK 自己产出最终 w"

这是本方案最省力的一点：不去重写 AES/RSA，而是找到提交方法后**由 SDK 自己算**。

```js
// 在 VM 里调用产品自己的提交方法
widget.$_BJJQ("<你的答案串>", passtime)   // 内部完成 JSON → AES → RSA → 自定义 base64
```

于是 Python 只要：把答案串喂进去 → 拿到 `w` → 按 `{gt, challenge, lang, pt, client_type, w}` 发到 `ajax.php`。

---

## 4. 答案构造：真机反解 `a` 的编码（本项目最关键的坑）

### 4.1 为什么要真机反解

代码里答案是 `a = tracker.$_FAA()`，而 tracker 由渲染器创建、里面存的是
`Math.round(100 * l)`，`l = (clientX - rect.left) / rect.width * 100`。

**光读代码会错**，因为：`rect` 到底是谁的矩形？图片怎么缩放？裁剪了多少？——这些只有真机量出来才算数。

### 4.2 真机取证手法（可复用）

1. 本地起静态服务，把**同版本的补丁文件**暴露在 `http://127.0.0.1:8791/`
2. 用浏览器 MCP 的 `navigate_page(initScript=...)` 劫持脚本加载：

```js
const d = Object.getOwnPropertyDescriptor(HTMLScriptElement.prototype, 'src');
Object.defineProperty(HTMLScriptElement.prototype, 'src', {
  configurable: true,
  get() { return d.get.call(this); },
  set(v) { if (v.includes('click.3.1.2')) v = 'http://127.0.0.1:8791/click.patched-widget.js';
           return d.set.call(this, v); }
});
```

> `127.0.0.1` 被 Chrome 视为可信来源，所以 https 页面加载它**不会**触发 mixed content 拦截。

3. 页面里就有 `window.__gt3Widget`（内部 widget）和 `window.__gt3Plain`（加密前明文）
4. 在真机上**用已知坐标点几下**，再点"确认"，然后读明文 / 读 `ajax.php` 响应

### 4.3 反解结果（逐位核对过）

```
a = "x1_y1,x2_y2,..."          # 下划线连坐标，逗号连点
x = round(10000 * (clientX - wrap.left) / wrap.width)
y = round(10000 * (clientY - wrap.top ) / wrap.height)
```

实例核对（真机 wrap = `(89.11, 203.64, 306.55, 306.55)`，点击事件坐标 `(171,414)`）：

```
(171 - 89.11) / 306.55 * 100 = 26.71  → round(100 × 26.71) = 2671
(414 - 203.64)/ 306.55 * 100 = 68.62  → round(100 × 68.62) = 6862
→ 提交的 a 里就是 "2671_6862"   ✓ 与服务器收到的完全一致
```

### 4.4 换算到"自然像素"（写求解器时用）

真机上量到的几何：

| 元素 | 尺寸 | 含义 |
|---|---|---|
| `.geetest_item_wrap` | **307×307（正方形）**，`overflow:hidden` | 可点击区，`background-size:100% auto` |
| `.geetest_item_img` | 307×**343** | 内层元素，高度是 wrap 的 112% |

轮次图自然尺寸 344×384，按宽度等比缩放到 307 宽 → 高 343，被 wrap 裁到 307 高。
所以自然像素 `(px,py)` 对应的比例是：

```
x = round(10000 * px / 图宽)
y = round(10000 * py / 图宽)      ← 注意：也是除以「图宽」！
```

> **我的原始错误**：y 除以了图高 384。真机反解后改成除以图宽 344，立刻从"全部 fail"变成 success。
> 原因是 wrap 是正方形且图按宽度等比缩放，**高 384 这个数根本不参与**。

### 4.5 ⚠️ 一个必须记住的假阳性陷阱

`.geetest_panel_success` 元素**在验证码刚出现时就已经存在于 DOM 里**（`display:none` 隐藏）。

```js
document.querySelector('.geetest_panel_success')   // 永远返回元素 → 判"成功"永远为真 ❌
```

我因此一度以为"随便点四个角也能过"，白高兴一场。正确判据二选一：

```js
getComputedStyle(document.querySelector('.geetest_panel_success')).display !== 'none'   // ✅
// 或直接读 ajax.php 的响应体（最权威）                                                  // ✅✅
```

---

## 5. 求解器：从轮次图到点击点

### 5.1 轮次图的固定结构（别用启发式去猜）

| 区域 | 位置 | 说明 |
|---|---|---|
| 可点击区 | 图的上方**正方形**（边长 = 图宽 344） | 下面的字都在这块里 |
| 提示词卡 | **底部 40 行 × 左侧 116 列** | 与真机 `.geetest_tip_img` 1:1 对应（`bgSize 298% 968%`、`bgPos 0% 100%`） |

> 坑：我一开始用"找白底矩形"的启发式定位提示词卡，在真机某一轮**定位到 y=323**（真值 344），
> 于是整卡 OCR 全乱。改成**固定几何**后稳定。**能固定就不要启发式。**

### 5.2 先定"要点几下"：字数 = 提示词字数

* 提示词可以是 **2~6 个字**，`spec` 字段（`"1*1"`）跟点数无关 → **绝不能写死**
* 早期我把 `topk` 写死 2 → 遇到 3 字提示词（`炸茄盒`、`酿冬瓜`）**必然失败**

最终判据（用字段字形反验字数）：

1. 对每个候选字数 n，把卡片等分成 n 格，收集每格的候选读数（两个 OCR 模型 × 多尺度 × 整卡/逐格）
2. **锚点**：某个字段字形有一个"强读数"（命中 ≥ 8 且 ≥ 2×次高），且该字恰好是某格的**最高票** → 计 1 个锚点
3. 锚点多者胜；平手再看"长度票数"，再平手看匹配比例与平均分

实测例子：真机一轮提示词是 **酿冬瓜**，标准模型把前两字并成 2 字「融岭」，beta 模型读出正确 3 字；
字段里有个字形被稳定读成 `瓜`（65 次 vs 次高 19 次）→ 只有 3 字方案能解释它 → 选 3 字 ✓

### 5.3 识别字形：不追求"读出真字"

**关键洞察**：OCR 的错误是**系统性**的。同一个模型会把卡片上的 `黄` 和字段里的 `黄` **读成同一个错字**（如 `鱼`）。

所以：**不需要读出真字，只需要"卡片格 ↔ 字段字形"的一致读数**。

```
score(卡片格 i, 字形 j) = Σ_ch min(卡片格 i 中 ch 的票数, 字形 j 被读成 ch 的次数)
```

* 按"候选字形的多少"从少到多贪心分配，每个字形只用一次
* 没有任何共同读数的格子（例如 `豆` 两个模型都读不出）**放到最后**处理，
  取"**自身身份最不自信**"的那个字形（`珠` 最强读数 38 次 vs `豆` 18 次 → 选 `豆`）
* 字形检测框要做两件事：**放大到中位尺寸**（检测器经常把字形裁小）、**合并重叠框**（它也会把一个字切成两个）

离线标注回归（`python check_v11.py`）：`黄包`、`爆炒田鸡`、`炸茄盒`、`鸡豆冰粉` → **4/4 通过**。

### 5.4 我试过但失败的路子（别重复走）

| 方法 | 结果 | 为什么不行 |
|---|---|---|
| 二值掩码 + IoU / chamfer | 不稳 | 提示词是**实心黑字**、字段是**霓虹描边**，两者不可比；单向 chamfer 还会把细模板塞进大色块得 0 分 |
| 对称 chamfer（补上反向项） | 分数挤在 39~42 | 掩码噪声主导，间距 <0.5 |
| `cv2.matchShapes`（Hu 矩） | 全在 2~6 之间 | 细笔画轮廓对矩不敏感，无判别力 |
| 梯度图 + NCC | 全部偏向同一字形 | 被背景**纹理**主导，不是字形 |
| 空心描边"填充"后 OCR | 更差 | 发光糊成一团 |
| 全局 S/V 阈值取霓虹 | 完全失效 | 字形与背景可能**同色系**（蓝紫字 + 橙色日落背景） |
| k-means 颜色聚类 | 出得了形状 | 但定不了**身份** |
| 提示词卡"找白框"启发式 | 真机偶发定位错 | 改用固定几何 |

---

## 6. 服务端到底校验什么（真机实验得出）

| 实验 | 结果 | 结论 |
|---|---|---|
| 点图像四个角（完全不在字形上） | `{"result":"fail"}` | **位置被校验** |
| 点对了字形但**顺序颠倒** | 面板未成功 | **顺序被校验** |
| 按提示词顺序点对 | `{"result":"success","score":"99"}` | 顺序 + 位置都要对 |
| 薄环境字段（`ep.ca:[]`、`tt` 仅 16 字符、`tm:-1`） | VM 仍 `success` | **该 gt 不因环境字段简陋而拒**（但不能假定所有站点都这样） |
| 真机 `score=1` 也放行 | 通过 | 放行阈值与**指纹/环境**相关；VM 路径服务端给 `score=14` 也放行 |

---

## 7. 踩坑总表（症状 → 根因 → 修法）

> 这一节是本文档最有价值的部分。每一条都是我真实踩过的。

### 7.1 判定与取证类

| # | 症状 | 根因 | 修法 |
|---|---|---|---|
| 1 | "随便点四角也 success" | `.geetest_panel_success` **一开始就在 DOM**（`display:none`） | 看 `getComputedStyle().display`，或直接读 `ajax.php` 响应体 |
| 2 | 以为目标是滑块 | 只看了"极验"就套模板 | 先跑真机抓预检 `result` 与加载的产品脚本，**形态由实测决定** |
| 3 | 截图保存到 `A:\...` 被拒 | MCP 截图有 workspace root 限制 | 用内联截图（不传 `filePath`） |
| 4 | `take_screenshot` 报 `No page found` | 浏览器标签被清了 | 先 `list_pages` 确认，再重新打开 |

### 7.2 免浏览器环境类

| # | 症状 | 根因 | 修法 |
|---|---|---|---|
| 5 | 请求序列停在第 6 个，**没有点选轮**、没有图片 | 补丁把 `,globalThis.x=o` 插进了 `var a=…,b=…` 的**声明列表** → `SyntaxError: Unexpected token '.'` → **整个资源静默不执行** | 注入必须是**语句**（放在 `var` 之前）；补丁产物**必须 `node --check`** |
| 6 | `error_104` / "get.php 请求失败" | 把延迟定时器**全部抽干**，触发了 SDK 自己的超时逻辑 | 用**虚拟时钟**，设每轮 drain 预算（`--timer-cap`） |
| 7 | `holder` 类名出现 `geetest_ie` | `'transition' in style` 四个厂商前缀全 false | 给 style 挂真实 `CSSStyleDeclaration` 原型 |
| 8 | `onReady` / `verify` 永不触发 | 从未触发 `<link>` 的 load | 捕获 link 并派发 load 事件 |
| 9 | 产品**一个 click 都不绑**（`withListeners: 0`） | 事件不冒泡 / 没有 body、head / 没有 `MouseEvent` | 补容器、补事件构造器、派发时冒泡 |
| 10 | `error_code 604`（用户回调异常） | 产品内部某处吞了异常（不致命） | 由驱动显式 `verify()` 绕过；604 仍会打点，忽略 |
| 11 | 拿到 w 却全是 664 长度但服务器说结构错 | 明文里 `a` 用数组（`[[x,y]]`）而不是字符串 | 见 §4：`a` 必须是 `"x_y,x_y"` |

### 7.3 答案与求解器类

| # | 症状 | 根因 | 修法 |
|---|---|---|---|
| 12 | 坐标编码一直 fail | y 除以了图高 384 | 改成除以**图宽**（wrap 是正方形） |
| 13 | 3 字提示词必挂 | `topk` 写死 2 | 字数由提示词决定（2~6） |
| 14 | 字数选了短的（`酿冬瓜`→读成 2 字） | "多数长度投票"在 2:3 平票时选短 | 改用**锚点**判据（强读数字形必须是某格最高票） |
| 15 | 答案永远是 `[[244,49],[212,212]]` | helper 里 `Array.isArray(reply.points)` 把**字符串答案**挡掉 → 走了兜底假点 | 接受 string 类型，并把 format 一起传下去 |
| 16 | 提示词卡 OCR 全乱 | "找白框"启发式定位到 y=323（真值 344） | 固定几何：底部 40 行 × 左侧 116 列 |
| 17 | 字形认不出（旋转 + 霓虹描边） | 单模型、单预处理 | **双模型（标准 + beta）并集** + **共同读数匹配** |
| 18 | 检测器把一个字切成两个框 / 把字形裁小 | 检测器固有误差 | 框放大到中位尺寸 + 合并重叠框 |

### 7.4 流程与成本类

| # | 症状 | 根因 | 修法 |
|---|---|---|---|
| 19 | 拿到 validate 后还在刷请求，冒出 `error_51`/`error_12` | helper 循环继续提交 | 解析到 `result:"success"` **立即 kill 子进程** |
| 20 | `python -c "..."` 里的补丁被改坏 | PowerShell 吃 `$`、`\|`、引号 | 用**脚本文件**或 edit 工具，不用 `-c` 拼长代码 |
| 21 | 请求额度被 bring-up 吃掉 | 调试期一轮几十个请求 | 稳态每轮 ≈11 个；调试时设 `--max-http` 硬上限 |

---

## 8. 验收：两条轨道都要跑

**轨道 A：免浏览器（交付路径）**

```powershell
python main.py --rounds 2
  round 1: SUCCESS validate=8853bdefeda3badc3bdded8e0c45c704 score=14 http=11 31.5s
  round 2: SUCCESS validate=e155b58f2ffdf6cd3d4d147889e46596 score=14 http=11 38.9s
successes 2/2
```

**轨道 B：真机浏览器（验证路径）**——新鲜 challenge，把求解器算出的点按序点下去，读 `ajax.php`：

| 轮 | 提示词 | 判决 |
|---|---|---|
| 1 | 动丽 | `{"result":"success","validate":"8f2ac79d6fb948e21cccee175f3753ff","score":"1"}` |
| 2 | 瓣藤 | `{"result":"success","validate":"8acab457191d1b47b44d2fd33c9c0eca","score":"1"}` |

验收标准（我最终采用的表述）：
> 对**新取**的 challenge，`/ajax.php` 返回带 `validate` 的 `success`，可重复 2~3 次，
> 且运行路径中**没有** 浏览器 / CDP / Playwright / Selenium（浏览器只用于取证与复核）。

---

## 9. 换一个站点时，按这个顺序做（可复用清单）

1. **侦察**：找业务侧"取参接口"（返回 `gt`+`challenge`）→ 确认是 Geetest；看世代（§1.2 对照表）
2. **定型**：真机跑一遍，抓**预检 `ajax.php` 的 `result`** 与随后加载的产品脚本 → 确定是滑块/点选/九宫格/…
3. **抓三个 `w`**：初始 / 预检 / 最终，记长度与结构（有没有 `.` + 256 hex）
4. **搭 VM**：Python 控 HTTP + `node:vm` 跑原码；先把"**请求序列与真机一致**"作为第一个里程碑
5. **导出提交方法**：最小补丁 + `__gt3Widget`，让 SDK 自己造最终 `w`
6. **反解答案编码**：在真机上用**已知点位**点几下，从明文/请求参数里反推出公式（§4.2）
7. **写求解器**：先把"点几下"定对（提示词字数），再解决"点哪里"
8. **双轨验收**：真机 + 免浏览器，各自留 `validate` 证据；顺手记录每轮 HTTP 成本

---

## 10. 命令速查 & 文件地图

### 10.1 常用命令

```powershell
cd A:\agent\work\bilibili\js_reverse_cache\tasks\bili-gt3-solver

python main.py --rounds 2                 # 免浏览器跑 2 轮（交付入口）
python gt3_protocol.py --max-http 20 --patched-core --patched-click `
       --call-widget '$_BJJQ' --answer-format pct --verify-first --timer-cap 2000
python check_v11.py                       # 求解器离线标注回归（应 4/4）
python app\server.py                      # 本地调试台 → http://127.0.0.1:8795/
python app\smoke_api.py 8795              # 用调试接口跑一轮并打印摘要

node --check cache\click.patched-widget.js   # 打完补丁必须校验
```

### 10.2 文件地图

| 文件 | 作用 |
|---|---|
| `main.py` | 交付入口：`--rounds N`，打印 validate |
| `gt3_protocol.py` | 协议驱动：取 challenge、应答全部 HTTP、解析判决（`[solve]`/`[verdict]`/`SUCCESS`） |
| `env/run.js` | VM 侧 helper（node:vm + env-patch + JSONL 协议） |
| `env/`（`bom/`、`dom/`） | 环境补丁模块（navigator / location / document …） |
| `patch_core.py`、`patch_click_widget.py` | 生成打了最小补丁的资源 + sha256 清单 |
| `gt3_click_solve_v11.py` | **当前求解器**（提示词过滤 + 双模型旋转 OCR 共同读数） |
| `gt3_click_api.py` | 驱动调用的求解器适配层（v11 → 点击点） |
| `check_v11.py` | 离线标注回归（4/4） |
| `app/server.py`、`app/ui/index.html` | 本地调试台（前端页面 + 调试接口） |
| `report.md` | 验收报告（证据、编码反解、校验边界、局限） |
| `PROGRESS.md` | 逐轮进展与结论（含走过的弯路） |
| `cache/` | 原始资源、补丁产物、字符串表、`proto_*/` 每轮证据（图片 + protocol.json + w_values.json） |

### 10.3 原始资源（自查用）

| 文件 | 大小 | sha256 前缀 |
|---|---|---|
| `fullpage.9.2.0-guwyxh.js` | 304,290 B | `923a147d…` |
| `slide.7.9.3.js` | 240,155 B | — |
| `click.3.1.2.js` | 226,572 B | `47c921354309c192…` |
| `geetest.6.0.9.js` | 208,020 B | — |
| `click_strings.tsv` / `fullpage_strings.tsv` | 11,969 / 19,989 条 | 运行时字符串表（用于反查混淆索引） |

---

## 11. 一页速记（Cheat Sheet）

```
判断是不是 GT      : 业务取参接口 data.type=="geetest" + 出现 api.geetest.com/gettype.php + geetest_ 类名
判断第几代         : GT3 = gt+challenge / gettype.php+get.php+ajax.php / w=密文+"."+256hex
判断哪种形态       : 预检 ajax.php 返回 {"result":"click"|"slide"}；再看加载 click.* / slide.*
                     click + pic_type=word → 文字点选
一轮请求           : gettype → fullpage.js → get.php(w=1452) → ajax(w=704, 定形态)
                     → click.js → get.php?is_next → gct.js → css → ajax(最终 w)
明文               : {lang, passtime, a, pic, tt, ep} (+站点附加 h9s9, rp)
答案 a             : "x1_y1,x2_y2"
                     x = round(10000*px/图宽)   y = round(10000*py/图宽)      ← 都除以图宽
点击区             : 轮次图上方的正方形（边长 = 图宽 344）
提示词卡           : 底部 40 行 × 左侧 116 列（固定几何，别猜）
判成功             : 读 ajax.php 响应体；不要用 querySelector('.geetest_panel_success')
```

---

*本文档基于一次完整实战整理；所有 validate、报文、坐标均已与真机逐位核对。*

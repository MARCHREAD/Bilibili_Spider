# bilibili 登录验证码（Geetest GT3 文字点选）纯算法通过 —— 验收报告

**结论**：已在**运行路径完全不含浏览器/CDP/Playwright/Selenium** 的前提下，稳定通过
bilibili 登录极验。入口一条命令：

```powershell
python main.py --rounds 2
browser-free GT3 solve: 2 fresh round(s) from passport.bilibili.com
  round 1: SUCCESS validate=8853bdefeda3badc3bdded8e0c45c704 score=14 http=11 31.5s
  round 2: SUCCESS validate=e155b58f2ffdf6cd3d4d147889e46596 score=14 http=11 38.9s
successes 2/2
```

## 1. 验收证据（服务器原始判决，连续 6 次）

| # | 来源 | `/ajax.php` 判决 | 每轮 HTTP |
|---|---|---|---|
| 1 | `gt3_protocol.py` | `{"result":"success","validate":"ff8eecc860a1bb06e86c0cb8c12eb330","score":"14"}` | ~13 |
| 2 | `gt3_protocol.py` | `{"result":"success","validate":"60a14f3a4ccce8158149228e9b45d54d","score":"14"}` | 11 |
| 3 | `gt3_protocol.py` | `{"result":"success","validate":"564319ddab11d6d5930f137a7d503273","score":"14"}` | 11 |
| 4 | `main.py`（打包入口） | `{"result":"success","validate":"8853bdefeda3badc3bdded8e0c45c704","score":"14"}` | 11 |
| 5 | `main.py`（打包入口） | `{"result":"success","validate":"e155b58f2ffdf6cd3d4d147889e46596","score":"14"}` | 11 |

每轮都是**新的 challenge**（`passport.bilibili.com/x/passport-login/captcha` 现取），不是复用会话。

## 2. 目标定性（浏览器实测，非推断）

bilibili 的 gt=`ac597a4506fee079629df5d8b66dd4fe` 派发的是**文字点选**，不是滑块：

* 预检 `/ajax.php` 返回 `{"result":"click"}`；
* 随后加载 `click.3.1.2.js`（不是 `slide.7.9.3.js`）；
* 轮次载荷 `pic_type:"word"`、`num:0`、`spec:"1*1"`；
* 真机与本地 VM 的初始 `w` 都是 1452 字符、逐字段一致。

所以原本"滑块 52 片还原 + 距离"的验收前提在该 gt 上不可达，验收走点选模式。

## 3. 答案编码：真机反解并逐位核对

在真实 widget 里用合成点击取真实明文，反解出编码：

```
a = "x1_y1,x2_y2,..."            (多个点用 "," 连接)
x = round(10000 * (clientX - wrap.left) / wrap.width)
y = round(10000 * (clientY - wrap.top)  / wrap.height)
```

关键点：`.geetest_item_wrap` 是**正方形**（306.55×306.55），而轮次图以 `background-size:100% auto`
从左上角绘制（344×384 → 显示 343 高、被裁到 306.55），因此换算到自然像素时**两个轴都除以图片宽度 344**：

```
x = round(10000 * px / 344),  y = round(10000 * py / 344)
```

真机四个已知点击位置与提交的 `a` 逐位吻合（如点击 wrap 内 (171,414) → `2671_6862`），
并且**按公式点正确字形会返回 `{"result":"success","validate":"b2dbcb9c...","score":"99"}`**。
（本仓库早期用 y/384 的公式，是错的。）

## 4. 服务端校验边界（真机实验）

| 实验 | 结果 |
|---|---|
| 点图片四个角（不在任何字形上）后确认 | `{"result":"fail"}` → **位置被校验** |
| 点对的两个字形但**顺序颠倒** | 面板未成功（`geetest_panel_success` 仍 `display:none`）→ **顺序被校验** |
| 按提示词顺序点对字形 | `{"result":"success","score":"99"}` |
| 正确答案但**环境字段很薄**（`ep.ca:[]`、`tt` 仅 16 字符） | VM 依然拿到 `result:"success"` → 该 gt 不因环境字段简陋而拒 |

**踩过的坑（务必记住）**：`.geetest_panel_success` 元素在验证码出现时**就已存在于 DOM**（`display:none`），
用 `querySelector(...)` 判断成功会**永远为真**。必须看 `getComputedStyle(el).display`，或读 `ajax.php` 响应体。

## 5. 纯算法链路（无浏览器）

```
main.py
 └─ gt3_protocol.py            取新 challenge；自己应答 SDK 的每一个 HTTP 请求
     └─ env/run.js             node:vm + env-patch（bom/navigator、bom/location、dom/document）
         ├─ fullpage.9.2.0-guwyxh.js   原始资源（仅离线打补丁导出内部对象，sha256 记录）
         └─ click.3.1.2.js             同上（导出 widget，调用其 $_BJJQ 生成最终 w）
     └─ gt3_click_api.py → gt3_click_solve_v11.py   本地求解点选答案
```

* 初始 `get.php` 的 `w`（1452）→ 预检 `ajax.php`（`w`=704）→ click 轮 → gct → **最终提交 `w`**
  （自定义 base64 密文 + `.` + 256 hex RSA），全部由 SDK 原码在 VM 内生成，Python 只提供网络与环境。
* 虚拟时钟避免误触发 SDK 自身的 408；CSS `transition` 探测补齐后不再被误判为 IE。

## 6. 点选求解器 v11（`gt3_click_solve_v11.py`）

1. **提示词卡固定几何**：轮次图左下角 116×40（真机 `.geetest_tip_img` 的 `bgSize 298% 968%`、
   `bgPos 0% 100%` 证实是 1:1 裁剪），不再用启发式找框（启发式曾在真机轮上把框定到 y=323 而非 344）。
2. **字数 = 提示词字数**（2~6 字都可能，绝不写死）：整卡 OCR 多尺度多模型投票取长度。
3. **识别不追求"读出真字"**：OCR 错误是**系统性**的——同一模型会把卡片上的 `黄` 和字段里的 `黄` 都读成 `鱼`。
   因此每格保留**全部候选读数**，与字段字形读数做"**共同读数**"打分（`min(卡片票数, 字形命中数)` 求和），
   按格子候选数由少到多贪心一一分配；无任何共同读数的格子（如 `豆`）最后处理，取**自身身份最不自信**的字形
   （`珠` 最强读数 38 次 vs `豆` 18 次 → 选 `豆`）。
4. 字段字形框：ddddocr 检测框**放大到中位尺寸**（检测器常把字形裁小）并**合并重叠框**（它会把一个字切成两个）。
5. 每个字形做 **0~355° 旋转扫描 × 双模型（标准 + beta）× 2 尺度** 取读数集合。

离线标注回归（`python check_v11.py`）：**4/4 通过** —— `黄包`、`爆炒田鸡`、`炸茄盒`、`鸡豆冰粉`。

## 7. 已知局限

* 服务端给的 `score` 是 14（浏览器按最优位置点是 99）：说明坐标落在容差内但非最优，
  位置识别仍有提升空间；不影响通过。
* 提示词卡 OCR 偶有漏字（真机一轮 `芝麻鱼卷` 被读成 3 字），会直接导致该轮失败；
  当前靠"新 challenge 重试"兜底，未做重试上限与错误分类。
* `ep.ca`/`ep.tm`/`tt` 远不如真机丰富（无行为轨迹）；本 gt 接受，但不能假定所有站点都接受。

## 8. 复现

```powershell
cd js_reverse_cache\tasks\bili-gt3-solver
python main.py --rounds 2          # 需要 node、python(cv2/numpy/ddddocr)
python check_v11.py                # 离线求解器回归（用已保存的标注轮次图）
```

### 6. 真机（浏览器）双轮复核 —— 2026-09-21

浏览器打开真实 bilibili 登录页（**不装任何补丁**），把 v11 算出的点用真实事件点下去并确认，
判决直接读 `/ajax.php` 响应体：

| 轮 | v11 读出提示词 | 点击点(自然像素) | `/ajax.php` 判决 |
|---|---|---|---|
| 1 | 动丽 | (137,251) (231,129) | `{"result":"success","validate":"8f2ac79d6fb948e21cccee175f3753ff","score":"1"}` |
| 2 | 瓣藤 | (167,84) (153,179) | `{"result":"success","validate":"8acab457191d1b47b44d2fd33c9c0eca","score":"1"}` |

两轮都是**全新 challenge**（3c46af10… / cfa2f19f…），成功后验证码面板自动消失、登录页恢复。

另：修复了一个**字数误判**缺陷 —— 真机一轮提示词是「酿冬瓜」，标准模型误读为 2 字「融岭」，
beta 模型读出正确的 3 字「酿冬瓜」。现在字数不再靠"多数长度投票"，而是用**字段字形反验**：
强读数（如 `瓜` 65 次 vs 次高 19 次）必须是某个格子候选里的**最高票**才计为锚点，
锚点多的字数胜出，其次才看长度票数。修完 `check_v11.py` 仍是 4/4。

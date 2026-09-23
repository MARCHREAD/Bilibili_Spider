# 本地调试台（GT3 文字点选）

一个纯本地的前端页面 + 调试接口，用来跑和看**免浏览器**的 GT3 求解链路。

## 启动

```powershell
cd js_reverse_cache\tasks\bili-gt3-solver
python app\server.py            # 默认 8795；可 python app\server.py 8800
# 打开 http://127.0.0.1:8795/
```

页面按钮：**跑 1 轮 / 跑 2 轮 / 跑 3 轮 / 停止**。每一轮都会现取一个新 challenge
（`passport.bilibili.com/x/passport-login/captcha`），完整跑一遍协议，不需要浏览器参与。

## 页面能看到什么

* **本次运行**：run id、challenge、提示词、字数、点击点、提交的 `a` 串、`validate`、`score`、
  HTTP 用量、三个 `w` 的长度（初始 1452 / 预检 704 / 最终 664）
* **求解明细（v11）**：字段字形检测框、每个格子的候选读数、最终匹配（含 score / fallback 标记）
* **轮次图**：原始 JPEG + 编号点击点（按自然像素 1:1 叠加）；右侧是 **2× 放大的提示词卡**
* **判决原文**：`ajax.php` 返回的原始 JSON
* **实时日志**：驱动逐行输出（轮询接口，不需要 websocket）
* **历史**：最近 30 次运行，点一行可回看它的日志与结果

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 测试页面 |
| GET | `/api/health` | `{"ok":true,"task":...}` |
| POST | `/api/run` | `{"rounds":1..5,"max_http":8..60}` → `{"run_id":...}` |
| GET | `/api/run/<id>?log_from=N` | 状态 + 解析后的摘要 + 新增日志行（`log_total` 用于下次 `log_from`） |
| POST | `/api/run/<id>/stop` | 终止当前子进程 |
| GET | `/api/runs` | 历史（最多 30 条） |
| GET | `/api/image/<id>/<file>` | 该轮保存的图片（轮次图 / 提示词卡素材） |

解析出的关键字段：`status / ok / gt / challenge / prompt / n_clicks / points / wire_answer /
verdict / validate / score / http_used / pic / w_values / solve / results`。

## 命令行等价物

```powershell
python app\smoke_api.py 8795     # 直接用接口跑一轮并打印摘要（不需要打开页面）
python main.py --rounds 2        # 不经过服务，直接跑两轮
python check_v11.py              # 求解器离线标注回归（4/4）
```

## 说明

* 页面只调用本机 `127.0.0.1`，不对外监听；服务是纯 stdlib（`ThreadingHTTPServer`），无额外依赖。
* 日志行数上限 4000（超出丢弃最旧的 1000 行），`log_from` 用绝对行号，前端按增量拉取。
* 想复核"真机也能过"时，用浏览器打开真实 bilibili 登录页，把页面里显示的**点击点**按顺序点下去即可
  （坐标为轮次图自然像素，换算到页面：`clientX = wrap.left + px * wrap.width / 344`）。

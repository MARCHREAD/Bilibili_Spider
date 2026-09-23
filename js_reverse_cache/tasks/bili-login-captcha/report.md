# bilibili 登录验证码协议取证报告

- 目标：`https://www.bilibili.com/?spm_id_from=333.1007.0.0` 的登录验证码实现方式
- 交付形态：`evidence` + `local-proof`（不做 collector / 不做验证码破解）
- 路由：`transport`（只读实时报文）+ `static-ast`（bundle 静态定位）
- gate family：`verifier-gated`，次标签 `transport-gated`
- 结论一句话：**bilibili PC 登录用的是极验 GT3（`fullpage` 9.2.0 / `slide` 7.9.3），由 passport 页面自己在登录前主动预取 `gt + challenge + token`，作答成功后把 `validate/seccode/challenge/token` 与 RSA 加密后的密码一起 POST 提交；另有"5 位字符图片码"作为第二条验证码通道。**

---

## 1. Startup Gate 与能力快照

| 项 | 值 |
|---|---|
| intake | `live-target` |
| browser mode | **`unavailable`**（工具注册表中无 `chrome-devtools` / `js-reverse` / `silent-value-capture` / Camoufox / reqable / HAR / PCAP） |
| `fingerprint_baseline_gap` | **存在** |
| `debugger_trace_gap` | **存在** |
| `silent_backend` | `absent` |
| curl impersonate | `chrome146`（锁定为本地 curl_cffi 实际最大版本，未套用更新的 live Chrome 大版本） |
| iv8 | missing（本次不需要） |
| 请求预算 | 声明 24，实际消耗 **20**（全部 GET，逐条记于 `network.jsonl`） |
| 账号/会话 | `none`（未登录、未使用任何账号态、未提交任何验证码答案） |

**必须明确的限制**：两个首选角色（`fingerprint-baseline`、`debugger-trace`）都没有可用手段，因此本报告**不声称"页面/运行时已被理解"**。全部结论来自两个**非浏览器证据面**：

1. **线上报文**（pure Python + curl_cffi，真实服务端响应）；
2. **静态 bundle**（passport SPA 的 hash 版本 chunk，本地窗口挖掘）。

这满足技能要求的"family 至少两个独立证据面相互印证"，但不满足 live-target 的双角色证据要求；缺失项已在第 7 节列明。

---

## 2. 证据面 A：真实线上报文

### 2.1 验证码预取（链路起点）

```
GET https://passport.bilibili.com/x/passport-login/captcha?source=main-fe-header
Referer: https://www.bilibili.com/
```
```json
{"code":0,"message":"OK","ttl":1,"data":{
  "type":"geetest",
  "token":"4e7a80b18bce4182b92dcf98e26991d0",
  "geetest":{"challenge":"93b3f49adcbd1a065550f55124cf592f",
             "gt":"ac597a4506fee079629df5d8b66dd4fe"},
  "tencent":{"appid":""}}}
```

样本（3 次独立 init，含 `source=main-fe` / `main-fe-header` / `blog`）：

| 字段 | 观察 |
|---|---|
| `gt` | **恒定** `ac597a4506fee079629df5d8b66dd4fe`（服务端固定站点 ID） |
| `challenge` | **每轮必换**（3/3 互不相同） |
| `token` | **每轮必换**（3/3 互不相同） |
| `type` | 均为 `geetest` |
| `tencent.appid` | 空串（腾讯 TDC 为预留分支，未启用） |

响应 224 字节、`application/json`、无 `Set-Cookie`：这个接口是**纯服务端下发挑战**，不带指纹绑定参数。

### 2.2 极验 GT3 两步注册（照 SDK 实际行为复现）

```
GET https://api.geetest.com/gettype.php?gt=ac597a...d4fe&callback=geetest_<ms>
→ {"status":"success","data":{"type":"fullpage",
    "static_servers":["static.geetest.com/","static.geevisit.com/"],
    "fullpage":"/static/js/fullpage.9.2.0-guwyxh.js",
    "slide":"/static/js/slide.7.9.3.js",
    "geetest":"/static/js/geetest.6.0.9.js", ...}}

GET https://api.geetest.com/get.php?gt=<gt>&challenge=<challenge>&lang=zh-cn&pt=0&client_type=web&callback=<jsonp>
→ {"status":"success","data":{"theme":"wind","s":"62614956",
    "c":[12,58,98,36,43,95,62,15,12], ...}}
```
且有 `Set-Cookie: GeeTestUser`。

**这两步是本报告判定 GT3 的第二个独立证据面**：`gettype.php` 的返回体是 GT3 专有结构；GT4 的标志字段（`captcha_id` / `lot_number` / `pow_detail` / `process_token` / `gcaptcha4.geetest.com/load`）在整个链路中**一次都没有出现**，按 `references/captcha-routing.md` 的判别表应排除 GT4。

### 2.3 第二条通道：5 位字符图片码（负对照）

```
GET https://api.bilibili.com/x/recaptcha/img?_=<rand>            → 200 {"code":-400,
      "message":"Key: 'Token' Error:Field validation for 'Token' failed on the 'required' tag"}
GET https://api.bilibili.com/x/recaptcha/img?_=<rand>&token=<伪造值>  → 200 image/jpeg 6298B（真 JPEG）
```
含义：该端点**要求 `token` 字段存在**（服务端 Go validator 的 `required` 规则），但对伪造值仍出图 ——
说明"图片码"这一路的挑战图本身不做 token 有效性校验，**真正的判定发生在提交端**（见 §4 未证明项）。

---

## 3. 证据面 B：前端 bundle 静态定位

`https://passport.bilibili.com/login` 只是一个 948 字节的 SPA 壳（`#passport-app`），全部逻辑在：

- 主包 `index.ed509056.js`（1.03 MB）→ **`geetest` / `captcha` 命中 0 次**
- rsbuild 异步 chunk 清单（从主包运行时提取）：`{10,263,264,409,600,832,838,86}`
- 逐 chunk 拉取后命中分布：

| chunk | 字节 | 关键命中 | 角色 |
|---|---|---|---|
| **264** | 207 KB | `geetest`×34, `captcha`×41, `/x/passport-login/`×8 | **PC 密码/短信登录页（主战场）** |
| 838 | 205 KB | `geetest`×32, `/x/passport-login/`×11 | 登录另一布局（渠道参数版） |
| 409 | 179 KB | `geetest`×35, `risk`×60, `safecenter` | 登录 + 安全中心 |
| 600 | 163 KB | `geetest`×33, `passport-user` | 改密/重置密码 |
| 10 / 263 / 86 / 832 | 88 / 83 / 88 / 2 KB | 无 | 扫码、授权等 |

### 3.1 内联的极验加载器（gt.js v0.0.0）

chunk 264 把极验官方 **gt.js 加载器整体内联**（不是外链 `gt.js`）：

```js
s.prototype = {
  api_server: "api.geetest.com",
  protocol: "http://",              // 实际被 e.https 或 t.location.protocol+"//" 覆盖为 https
  typePath: "/gettype.php",
  fallback_config: {
    slide:    {static_servers:["static.geetest.com","static.geevisit.com"], slide:"/static/js/geetest.0.0.0.js"},
    fullpage: {static_servers:["static.geetest.com","static.geevisit.com"], fullpage:"/static/js/fullpage.0.0.0.js"}
  },
  _get_fallback_config(){ return a(this.type) ? this.fallback_config[this.type]
                            : (this.new_captcha ? this.fallback_config.fullpage : this.fallback_config.slide) }
};
window.initGeetest = function(e, r){ ... }   // e.gt / e.challenge 被写入 window.GeeGT / window.GeeChallenge
```
它内部 `f(server, typePath, cfg, cb)` 会先 `e.replace(/^https?:\/\/|\/$/g,"")` 归一化 server 名，再拼
`?gt=..&callback=..` 发起 §2.2 的 `gettype.php`。→ 与线上抓包一致（本地自检已验证）。

### 3.2 业务侧包装（Promise 化的 geetest 调用）

```js
var s = function(t){ var e=t.config, r=t.el, n=t.async, o=t.onReady, s=t.onSuccess, a=t.onError, u=t.onClose;
  return new Promise(function(t,c){
    var f=window.initGeetest;
    if(!f){ a({code:-1,status_code:-1,message:"geetest初始化失败"}); return c(...) }
    var p = e?.offline ?? false,
        g = e?.new_captcha ?? true,     // 默认 true -> 走 fullpage
        v = e?.product || "bind",       // 站点未传 product，默认 "bind"
        m = e?.width || "100%";
    f({...e, offline:p, new_captcha:g, product:v, width:m}, function(e){
      e.onReady(...);
      "bind"===v ? (n&&r ? r.onclick=()=>e.verify() : e.onReady(()=>e.verify()))
                 : (r && e.appendTo(r));          // 本站未传 el，故直接 verify() 弹面板
      e.onSuccess(function(){ var r=e.getValidate(); if(r){
        s?.({data:{geetest_challenge:r.geetest_challenge,
                   geetest_seccode:r.geetest_seccode,
                   geetest_validate:r.geetest_validate}, captcha:e}) } });
      e.onError(.../* code:-2 "geetest实例化失败" */); e.onClose(...);
    })
  })
};
```

### 3.3 验证码组件 `captcha-img-dialog`（双通道分叉点）

```js
name:"captcha-img-dialog", props:{ preFunc: Function },
data: ()=>({ pre_info:{type:"", token:"", geetest:{challenge:"", gt:""}},
            callback:{}, show_img_dialog:false, img_code:"" }),
mounted(){ this.preCode() },                                   // 挂载即预取
methods:{
  preCode(){ this.preFunc({source: this.$route.query.source || "main-fe"})
               .then(t=>{ 0===t.code ? this.parseData(t.data) : toast(t.message||"验证码预取失败") }) },
  parseData(t){ if(t.recaptcha_type){                          // ← 第二种 schema
      this.pre_info = {type:t.recaptcha_type, token:t.recaptcha_token,
                       geetest:{challenge:t.gee_challenge, gt:t.gee_gt}} }
    else this.pre_info = t },                                  // ← 当前线上命中的 schema
  showCaptcha(){ return new Promise((res,rej)=>{ this.callback={resolve:res,reject:rej};
      "geetest"===this.pre_info.type ? this.initGeeCode() : this.show_img_dialog=true }) },
  initGeeCode(){ geetestWrapper({ config:{ gt:this.pre_info.geetest.gt,
        challenge:this.pre_info.geetest.challenge, offline:false, lang:langCode() },
      onSuccess: t=>{ let {data:e}=t,
        r = { captcha_type:this.pre_info.type, validate:e.geetest_validate,
              seccode:e.geetest_seccode, challenge:e.geetest_challenge,
              token:this.pre_info.token };
        this.callback.resolve(r); this.preCode() },             // 成功后立刻再预取下一轮
      onError: t=>{ report({type:"appear", event:"CaptchaAlternatives"}); this.callback.reject(t) },
      onClose: t=>{ this.preCode(); this.callback.reject("关闭弹窗") } }) },
  submit(){ this.isSubmit && (this.callback.resolve({captcha_type:"img",
              token:this.pre_info.token, img_code:this.img_code}), ...) },
  computed:{ isSubmit(){ return 5===this.img_code.length },     // 图片码固定 5 位
    captcha_url(){ return this.pre_info.token && "geetest"!==this.pre_info.type
        ? `//api.bilibili.com/x/recaptcha/img?_=${Math.random()}&token=${this.pre_info.token}` : "" } } }
```
UI 侧：标题「安全校验」、输入框 placeholder「输入图片中的字符」、`maxlength="5"`、按钮「换一张」→ 再次 `preCode()`。

### 3.4 登录提交拼参（验证码字段的最终消费者）

```js
// 模块 2086：接口层
YF = t => GET ("/x/passport-login/captcha", t)               // 验证码预取
R1 = t => POST("/x/passport-login/web/login", t, [raw])      // 密码/短信码登录
Aq = t => GET ("/x/passport-login/web/sms/send", t)          // 发短信
lT = async pwd => { let e = await GET("/x/passport-login/web/key", {_: Date.now()});
                    if(0!==e.code) return "";
                    let r = new JSEncrypt(); r.setPublicKey(e.data.key);
                    return r.encrypt(e.data.hash + pwd) }    // ← RSA( hash + 密码 )

// 密码登录
login(){ this.isCanLogin
  ? this.validate() && this.$refs.captcha.showCaptcha().then(t=>this.handlerLogin(t)).catch(()=>{})
  : toast("请先勾选同意") },                                  // ← 每次点登录都先过验证码组件

async handlerLogin(t){
  let e = await lT(this.subForm.password);
  let r = { source, sns_platform, sns_openid, csrf_state,
            username: this.subForm.username, password: e, go_url };
  r = "geetest"===t.captcha_type
      ? Object.assign(r, { validate:t.validate, token:t.token,
                           seccode:t.seccode, challenge:t.challenge })
      : Object.assign(r, { captcha:t.img_code, token:t.token });
  R1(r).then(t=>{ 0===t.code ? (0!==t.data.status ? location.replace(t.data.url) : this.setCookie(t.data))
                            : toast(t.message).then(()=>{[86667,86669,86670].includes(t.code) && (sns_info.checked="sms")}) })
}

// 短信通道复用同一验证码组件
sendSms(){ ... this.$refs.captcha.showCaptcha().then(t=>this.sendPhoneCode(t)) },
sendPhoneCode(t){ let e={source, tel, cid};
  e = "geetest"===t.captcha_type ? {...e, validate, token, seccode, challenge} : {...e, captcha:t.img_code, token};
  Aq(e).then(t=>{ 0===t.code ? (this.captcha_key=t.data.captcha_key, 60s 倒计时) : toast(t.message) }) }
```

**关键点**：提交体里**不含 `captcha_type` 字段** —— 通道靠"字段集合互斥"表达：极验通道给 `validate/seccode/challenge`，图片通道给 `captcha`，两者都带 `token`。

---

## 4. 完整链路时序

```
[用户点开登录]
  1. GET  passport.bilibili.com/x/passport-login/captcha?source=main-fe
          ← { type:"geetest", token:<每轮>, geetest:{ gt:<固定>, challenge:<每轮> } }
          （组件 mounted 即预取，不是失败后才取）

[极验通道 type==="geetest"]
  2. 内联 gt.js: initGeetest({gt, challenge, offline:false, new_captcha:true, product:"bind", lang})
  3. GET  api.geetest.com/gettype.php?gt=..&callback=..      ← type:"fullpage" + 资源清单
  4. 从 static.geetest.com 加载 fullpage.9.2.0-guwyxh.js / slide.7.9.3.js（渲染拼图/滑块）
  5. GET  api.geetest.com/get.php?gt=..&challenge=..&pt=0&client_type=web  ← 本轮 c/s 挑战数据
  6. 用户拖动滑块 → SDK 本地生成加密 w → 极验侧校验 → getValidate()
          → { geetest_challenge, geetest_validate, geetest_seccode }
  7. 前端立刻 preCode() 预取下一轮（challenge/token 一次性语义）

[图片通道 type!=="geetest"]（当前 source 未命中，代码路径存在）
  2'. GET api.bilibili.com/x/recaptcha/img?_=<rand>&token=<token>  ← 5 位字符图
  3'. 用户输入 5 位 → { captcha_type:"img", token, img_code }

[提交]
  8. GET  passport.bilibili.com/x/passport-login/web/key?_=<ms>  ← { key, hash }
  9. password = RSA_JSEncrypt(pubkey).encrypt(hash + 明文密码)   （PKCS#1 v1.5）
 10. POST passport.bilibili.com/x/passport-login/web/login   (x-www-form-urlencoded)
       geetest 通道: source,sns_platform,sns_openid,csrf_state,username,password,
                     go_url,validate,token,seccode,challenge
       图片  通道:  …,captcha=<5位>,token
 11. code=0 → data.status!==0 ? location.replace(data.url) : 落 cookie
     code≠0 → toast(message)；（86667/86669/86670 切到短信登录）
```

---

## 5. 动态值来源与归属分类

| 字段 | 来源类别 | 归属 | 生命周期 | 写入者/刷新路径 |
|---|---|---|---|---|
| `gt` | `fixed`（站点 ID） | server-owned | 长期 | 服务端配置，3 轮采样恒定 |
| `challenge` | `server-issued` | server-owned | **单轮** | `GET /x/passport-login/captcha` 每次调用刷新 |
| `token` | `server-issued` | server-owned | **单轮** | 同上；成功后 `preCode()` 主动再取 |
| `geetest_challenge/validate/seccode` | `risk-interactive` | host-owned（极验 SDK 产出） | 单轮 | 由用户在极验面板完成作答后 `getValidate()` 返回 |
| `c` / `s`（GT3 挑战数据） | `server-issued` | 极验 server-owned | 单轮 | `get.php` 每次会话下发 |
| GT3 提交用 `w` | `local-algorithm` + `host` 混成 | host-owned | 单轮 | 极验 slide/fullpage JS 本地加密生成（含轨迹、耗时） |
| `password` | `local-algorithm` | python/host 均可复现 | 单次 | `RSA(hash + pwd)`，`hash`/`key` 来自 `/web/key` |
| `img_code` | 用户输入 | — | 单轮 | 5 位字符，长度即校验门槛 |
| `source` | `plaintext` | python-owned | 常量 | 由路由 query 决定，默认 `main-fe` |
| 会话 Cookie（`buvid3`、`b_nut`…） | `server-issued` | server-owned | 会话 | 首页首次响应种下 |

首页侧旁证：首页 HTML 的 whiteScreen 探测列表里包含 **`.geetest_panel_ghost`**，错误过滤器白名单含 **`static.geetest.com`** —— 说明**首页弹窗登录同样挂极验面板**，与你给的 URL 直接相关。

---

## 6. 本地证明（local-proof，12/12 通过）

`captcha_contract.py`（无联网、无参数、直接运行）：

1. 3 个**真实** legacy init 样本 → 全部归一化为 `{type, token, gt, challenge}`；
2. `gt` 三样本恒定、`challenge`/`token` 三样本互不相同（一次性语义）；
3. 合成 `recaptcha_*` schema 向量 → 映射到同一契约（双 schema 兼容分支正确）；
4. `handlerLogin` 拼参：极验通道 `{validate,seccode,challenge,token}` 且**无** `captcha`；
   图片通道 `{captcha,token}` 且**无** `validate/seccode/challenge`；短信通道复用同一规则；
5. 密码在提交前必为 RSA 密文（无明文路径）；
6. **跨证据面交叉校验**：线上 `gettype.php` 的 `type:"fullpage"` 命中内联加载器 `fallback_config` 的键；
   `static_servers` 在施加加载器自身的 `replace(/^https?:\/\/|\/$/g,"")` 归一化后与加载器常量一致；
   线上 `get.php` 返回同轮 `c`/`s` 挑战数据。

自检过程本身也暴露并修正了我第一版比对逻辑的一个 bug（尾斜杠归一化），修正后重跑全绿。

---

## 7. 未证明项与盲区（必须如实标注）

1. **无浏览器角色证据**：`fingerprint-baseline` 与 `debugger-trace` 均未取得，未在真实浏览器中观察过极验面板渲染与 `w` 生成过程。因此**不能声称理解页面运行时**；本报告的"前端行为"来自静态 chunk 语义 + 线上报文一致性，而非运行时追踪。
2. **未提交登录**：`POST /x/passport-login/web/login` 一次都没有发出（尊重"不使用账号/不提交"授权），故**服务端对验证码的最终判定语义未验证**——包括"validate 过期/复用"的具体错误码。
3. **未驱动作答**：滑块/图片码答案未生成、未提交；GT3 的 `ajax.php`(validate) 完成步骤与 `w` 构造未复现（本任务形态不需要，也不交付破解路径）。
4. **图片通道当前是否真会被下发**：代码分支存在且在线上 bundle 里，但我测试的 3 个 `source` 都返回 `type:"geetest"`。图片通道是否只对特定 source/风控等级启用，**未经证实**。
5. **`recaptcha_*` schema 未被线上命中**：该分支只在静态代码中存在，属"代码存在、线上未触发"。
6. `Set-Cookie: GeeTestUser`（极验域）与 `buvid3`/`b_nut`（bilibili 域）的跨轮复用边界未做消融实验。

按 `references/failure-surface-taxonomy.md` 归类：以上属 **工具链角色缺失（capability gap）** 与 **未行使的授权边界（authority boundary）**，不是协议理解失败。

---

## 8. 产物清单（`js_reverse_cache/tasks/bili-login-captcha/`）

| 文件 | 说明 |
|---|---|
| `report.md` | 本报告 |
| `task.json` | work order（shape / route / permissions / budget / capability snapshot） |
| `network.jsonl` | 20 条只读请求流水（url / status / len） |
| `captcha_contract.py` | **local-proof 自检模块**（12 项断言，无联网） |
| `captcha_flow.json` | 自检产出的协议契约 + 端点表 + 未证明项 |
| `probe_captcha.py` / `probe_controls.py` / `probe_img_fix.py` / `fetch_assets.py` / `fetch_chunks.py` | 取证脚本（GET only） |
| `mine_local.py` / `mine_login_chunk.py` / `mine_login_chunk2.py` / `mine_login_chunk3.py` | 本地窗口挖掘脚本 |
| `static_findings.json` / `local_mine.json` / `chunk_findings.json` / `login_chunk_windows*.json` / `control_probes.json` | 挖掘与对照结果 |
| `raw/`（20 个文件，2.3 MB） | 原始报文：init JSON×3、`gettype.php`/`get.php` JSONP、登录页 HTML、首页 HTML、SPA 主包、8 个 chunk、图片码对照 JPEG |

**浏览器无关性**：全部取证与自检均为纯 Python（curl_cffi + 标准库），无浏览器自动化、无浏览器 profile、无页面驱动、无采集后端；`captcha_contract.py` 完全不联网。

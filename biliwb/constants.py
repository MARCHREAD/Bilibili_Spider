"""常量：端点、WBI 混淆表、错误码语义。

所有端点均来自 live 报文取证（见 js_reverse_cache/tasks/bili-workbench/）。
"""

from __future__ import annotations

# ---------------------------------------------------------------- WBI

# wbi 混淆表的取值顺序（对 img_key + sub_key 做重排后取前 32 位作为 mixin_key）
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

# ---------------------------------------------------------------- 端点

API = "https://api.bilibili.com"
PASSPORT = "https://passport.bilibili.com"
WWW = "https://www.bilibili.com"

EP_NAV = f"{API}/x/web-interface/nav"
EP_SPI = f"{API}/x/frontend/finger/spi"
EP_TICKET = f"{API}/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket"

EP_QR_GENERATE = f"{PASSPORT}/x/passport-login/web/qrcode/generate"
EP_QR_POLL = f"{PASSPORT}/x/passport-login/web/qrcode/poll"
EP_COOKIE_INFO = f"{PASSPORT}/x/passport-login/web/cookie/info"
EP_LOGIN_KEY = f"{PASSPORT}/x/passport-login/web/key"
EP_LOGIN = f"{PASSPORT}/x/passport-login/web/login"

# 验证码预取：必须在**即将提交登录的那个会话**里调用。
# 服务端把 token 与 challenge 绑在预取请求上，且订单式过期（实测：过期的
# challenge 会让登录端返回 -105/-662，而登录端**先查验证码再查账号密码**）。
EP_CAPTCHA = f"{PASSPORT}/x/passport-login/captcha"

EP_SEARCH_TYPE = f"{API}/x/web-interface/wbi/search/type"
EP_SEARCH_USER = f"{API}/x/web-interface/wbi/search/type"

EP_VIEW = f"{API}/x/web-interface/wbi/view"
EP_VIEW_DETAIL = f"{API}/x/web-interface/wbi/view/detail"
EP_TAGS = f"{API}/x/tag/archive/tags"
EP_PLAYER_V2 = f"{API}/x/player/wbi/v2"
EP_SUBTITLE_WEB = f"{API}/x/v2/subtitle/web/view"
EP_PLAYURL = f"{API}/x/player/wbi/playurl"

EP_REPLY_MAIN = f"{API}/x/v2/reply/wbi/main"
EP_REPLY_SUB = f"{API}/x/v2/reply/reply"
EP_REPLY_DESC = f"{API}/x/v2/reply/subject/description"

EP_DM_VIEW = f"{API}/x/v2/dm/web/view"
EP_DM_SEG = f"{API}/x/v2/dm/wbi/web/seg.so"

EP_ACC_INFO = f"{API}/x/space/wbi/acc/info"
EP_ARC_SEARCH = f"{API}/x/space/wbi/arc/search"
EP_NAVNUM = f"{API}/x/space/navnum"
EP_SETTING = f"{API}/x/space/setting"
EP_UPSTAT = f"{API}/x/space/upstat"
EP_RELATION_STAT = f"{API}/x/relation/stat"
EP_FOLLOWINGS = f"{API}/x/relation/followings"
EP_FOLLOWERS = f"{API}/x/relation/followers"
EP_ELEC = f"{API}/x/ugcpay-space/stat"          # 实测 404，已改用 acc/info.elec.show_info.total
EP_CARD = f"{API}/x/web-interface/card"

EP_DYN_SPACE = f"{API}/x/polymer/web-dynamic/v1/feed/space"

# 视频页 HTML（用于页面级取证：__INITIAL_STATE__、广告披露标签）
EP_VIDEO_PAGE = f"{WWW}/video/{{bvid}}/"

# ---------------------------------------------------------------- 业务枚举

SEARCH_ORDERS = {
    "totalrank": "综合排序",
    "click": "最多播放",
    "pubdate": "最新发布",
    "dm": "最多弹幕",
    "stow": "最多收藏",
}

SEARCH_DURATIONS = {
    0: "全部时长",
    1: "10分钟以下",
    2: "10-30分钟",
    3: "30-60分钟",
    4: "60分钟以上",
}

# ---------------------------------------------------------------- 错误码

CODE_OK = 0
CODE_NOT_LOGIN = -101
CODE_RISK = -352          # 风控校验失败
CODE_ACCOUNT_BAN = -412
CODE_NOT_FOUND = -404
CODE_PRIVACY = -400       # 常见于隐私受限 / 参数无效

HTTP_RISK = 412           # 返回 HTML 风控页

ERROR_SEMANTICS = {
    0: "成功",
    -101: "账号未登录（该数据需要登录态）",
    -352: "风控校验失败（-352）：需要补齐 buvid/bili_ticket 或降低频率",
    -400: "请求错误 / 对方隐私设置限制",
    -403: "访问权限不足",
    -404: "什么也没有找到",
    -412: "请求被拦截（账号风控）",
    62002: "稿件不可见",
    62004: "稿件审核中",
}

# ---------------------------------------------------------------- 网络身份

# 传输身份锁定为本地 curl_cffi 实际最大 chrome 版本，不套用 live 浏览器更新的大版本。
IMPERSONATE = "chrome"

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
)

# live 报文实测的 gaia 指纹槽位（取自样本，作为显式配置输入，非运行时读取）
GAIA_DM_IMG_STR = "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ"
GAIA_DM_COVER_IMG_STR = (
    "QU5HTEUgKE5WSURJQSwgTlZJRElBIEdlRm9yY2UgUlRYIDQwNjAgTGFwdG9wIEdQVSAoMHgwMDAwMjhFMCkg"
    "RGlyZWN0M0QxMSB2c181XzAgcHNfNV8wLCBEM0QxMSlHb29nbGUgSW5jLiAoTlZJRElBKQ"
)
GAIA_DM_IMG_INTER = '{"ds":[],"wh":[4667,4319,101],"of":[499,998,499]}'

DEVICE_REQ_JSON = '{"platform":"web","device":"pc","mobi_app":"web_cn"}'
LOCALE_JSON = '{"c_locale":{"language":"zh","script":"Hans"},"always_translate":false}'

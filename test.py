import requests
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

headers = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9",
    "origin": "https://www.bilibili.com",
    "priority": "u=1, i",
    "referer": "https://www.bilibili.com/",
    "sec-ch-ua": "\"Google Chrome\";v=\"153\", \"Not_A Brand\";v=\"8\", \"Chromium\";v=\"153\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36"
}
cookies = {
    "buvid3": "5A298E17-4A5F-EE75-7F8D-31A863229F4625420infoc",
    "b_nut": "1789020925",
    "_uuid": "485210192-17BB-8A54-755A-ADC62AFAD85325965infoc",
    "buvid_fp": "3f9be97aa2a0343cd7753ce1e1ef838b",
    "buvid4": "1979E47C-25C6-015C-04E2-241D40F14A1A27802-026091014-UzpQof1dl4BD4ak3Kv/Z4Q%3D%3D",
    "theme-tip-show": "SHOWED",
    "rpdid": "|(J|)Yu~)Y)R0J'u~)m|kukYu",
    "theme-avatar-tip-show": "SHOWED",
    "CURRENT_QUALITY": "80",
    "bsource": "search_google",
    "bili_ticket": "eyJhbGciOiJIUzI1NiIsImtpZCI6InMwMyIsInR5cCI6IkpXVCJ9.eyJleHAiOjE3OTAyNDMyMDMsImlhdCI6MTc4OTk4Mzk0MywicGx0IjotMX0.hLCcUqSKhofScnLITD3ZojQ_AaNxcLjvk54lGdcCsEk",
    "bili_ticket_expires": "1790243143",
    "bp_t_offset_494757969": "1250460860439068672",
    "CURRENT_FNVAL": "2000",
    "home_feed_column": "4",
    "browser_resolution": "686-730",
    "sid": "gya5em9p",
    "b_lsid": "B1E927AE_1A0C3A6F94C"
}
url = 'https://api.bilibili.com/x/player/wbi/playurl'
params = {
    "avid": "116453307129105",
    "bvid": "BV1B4oYBAEaZ",
    "cid": "37749721527",
    "qn": "32",
    "fnver": "0",
    "fnval": "2000",
    "fourk": "1",
    "gaia_source": "view-card",
    "from_client": "BROWSER",
    "is_main_page": "false",
    "need_fragment": "false",
    "isGaiaAvoided": "true",
    "client_attr": "0",
    "version_name": "4.10.4",
    "app_id": "100",
    "session": "bdcbe682d49bf96b0f0420d56d22f588",
    "voice_balance": "1",
    "web_location": "1315873",
    "dm_img_list": "\\[{\"x\":1279,\"y\":287,\"z\":0,\"timestamp\":10848,\"k\":102,\"type\":0},{\"x\":1306,\"y\":315,\"z\":24,\"timestamp\":10950,\"k\":110,\"type\":0},{\"x\":1295,\"y\":201,\"z\":184,\"timestamp\":11051,\"k\":102,\"type\":0},{\"x\":1133,\"y\":15,\"z\":94,\"timestamp\":11152,\"k\":109,\"type\":0},{\"x\":1161,\"y\":33,\"z\":175,\"timestamp\":11254,\"k\":71,\"type\":0},{\"x\":975,\"y\":-150,\"z\":49,\"timestamp\":11355,\"k\":83,\"type\":0},{\"x\":1190,\"y\":62,\"z\":296,\"timestamp\":11457,\"k\":110,\"type\":0},{\"x\":1021,\"y\":-108,\"z\":130,\"timestamp\":11561,\"k\":109,\"type\":0},{\"x\":1176,\"y\":56,\"z\":281,\"timestamp\":12237,\"k\":108,\"type\":0},{\"x\":1086,\"y\":52,\"z\":117,\"timestamp\":12337,\"k\":126,\"type\":0},{\"x\":1894,\"y\":880,\"z\":865,\"timestamp\":12438,\"k\":77,\"type\":0},{\"x\":2146,\"y\":1135,\"z\":1108,\"timestamp\":12541,\"k\":116,\"type\":0},{\"x\":1551,\"y\":543,\"z\":504,\"timestamp\":12675,\"k\":121,\"type\":0},{\"x\":2762,\"y\":1873,\"z\":967,\"timestamp\":12782,\"k\":89,\"type\":0},{\"x\":2663,\"y\":1901,\"z\":303,\"timestamp\":12887,\"k\":121,\"type\":0},{\"x\":2804,\"y\":1237,\"z\":191,\"timestamp\":15836,\"k\":91,\"type\":0},{\"x\":2568,\"y\":830,\"z\":353,\"timestamp\":15936,\"k\":63,\"type\":0},{\"x\":2462,\"y\":718,\"z\":265,\"timestamp\":16036,\"k\":80,\"type\":0},{\"x\":3007,\"y\":1263,\"z\":810,\"timestamp\":16139,\"k\":95,\"type\":3},{\"x\":3293,\"y\":1556,\"z\":1098,\"timestamp\":16240,\"k\":102,\"type\":0}\\]",
    "dm_img_str": "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ",
    "dm_cover_img_str": "QU5HTEUgKEludGVsLCBJbnRlbChSKSBVSEQgR3JhcGhpY3MgKDB4MDAwMEE3OEIpIERpcmVjdDNEMTEgdnNfNV8wIHBzXzVfMCwgRDNEMTEpR29vZ2xlIEluYy4gKEludGVsKQ",
    "dm_img_inter": "{\"ds\":\\[{\"t\":5,\"c\":\"\",\"p\":\\[1342,76,909\\],\"s\":\\[133,1134,694\\]}\\],\"wh\":\\[3069,2093,79\\],\"of\":\\[493,986,493\\]}",
    "x-bili-device-req-json": "{\"platform\":\"web\",\"device\":\"pc\",\"mobi_app\":\"web_cn\"}",
    "x-bili-locale-json": "{\"c_locale\":{\"language\":\"zh\",\"script\":\"Hans\"},\"always_translate\":false}",
    "w_rid": "5fe5b56d8f9dbb26d14235a4beeb9ff0",
    "wts": "1789988895"
}
response = requests.get(url, headers=headers, cookies=cookies, params=params)

print(response.text)
print(response)
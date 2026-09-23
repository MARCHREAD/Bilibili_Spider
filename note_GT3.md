# 极验3(GT3)验证码破解思路
##他妈的傻逼deepseekv4.1逆向补环境不补原型链的都来了
草泥马
干你妈四十分钟 老子自己试都试出来了，神了。##

完整复现浏览器中的两阶段协议链，把浏览器当做前期的取证工具，最终由python请求链和少量的本地JS helper来完成验证

整体链路是：
    业务注册接口
    → GT3 类型确认
    → fullpage 初始 get.php
    → fullpage 预检测 ajax.php
    → 获取滑块图片和新 challenge
    → 计算缺口与轨迹
    → slide 最终 ajax.php
    → 将 validate 交给业务网站

## 具体过程

### 1.从业务接口获取初始化参数
 

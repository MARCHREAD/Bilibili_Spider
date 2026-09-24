@echo off
chcp 936 >nul
title bilibili 本地采集工作台
cd /d "%~dp0"

echo.
echo   ============================================================
echo     bilibili 本地批量采集工作台
echo     纯 Python . 无浏览器 . 协议级只读采集
echo   ============================================================
echo.

rem ---------------------------------------------------------- 1/3 Python
set "PY=python"
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo   [x] 没有找到 Python。
        echo.
        echo       请先安装 Python 3.10 或更高版本：
        echo         https://www.python.org/downloads/
        echo       安装时务必勾选 "Add python.exe to PATH"。
        echo.
        pause
        exit /b 1
    )
    set "PY=py -3"
)

%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 (
    echo   [x] Python 版本过低，需要 3.10 或更高。当前版本：
    %PY% --version
    echo.
    pause
    exit /b 1
)
echo   [1/3] Python 就绪
%PY% --version
echo         命令    : %PY%
echo         工作目录: %CD%

rem ---------------------------------------------------------- 2/3 依赖
%PY% -c "import curl_cffi, fastapi, uvicorn, segno" >nul 2>nul
if not errorlevel 1 goto :deps_ok

echo   [2/3] 缺少运行依赖
echo.
choice /c YN /n /m "         现在自动安装? [Y=安装 / N=退出] "
if errorlevel 2 goto :deps_cancel
echo.
%PY% -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo   [x] 依赖安装失败。请手动执行：
    echo         %PY% -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo   [2/3] 依赖安装完成
goto :launch

:deps_ok
echo   [2/3] 依赖已就绪

rem ---------------------------------------------------------- 3/3 启动
:launch
echo   [3/3] 正在启动  http://127.0.0.1:8765/
echo.
echo         浏览器会自动打开；关闭本窗口即停止服务。
echo         ------------------------------------------------------
echo.

%PY% main.py
set "RC=%errorlevel%"

if not "%RC%"=="0" (
    echo.
    echo   [x] 工作台异常退出（错误码 %RC%）
    echo.
    echo       端口被占用是最常见的原因。关掉上一个工作台窗口，或改用其它端口：
    echo         %PY% main.py --port 8766
    echo.
    pause
)
exit /b %RC%

:deps_cancel
echo.
echo   已取消。请先安装依赖再运行：
echo     %PY% -m pip install -r requirements.txt
echo.
pause
exit /b 1

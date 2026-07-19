@echo off
cd /d "%~dp0"
title Claude Gateway - Sakurafrp 首次配置
echo.
echo ================================================
echo		[1/4] 注册 下载 Sakurafrp 启动器
echo ================================================
echo.
echo   浏览器正在打开下载页...
echo   若无反应复制到浏览器 https://www.natfrp.com/tunnel/download
echo  (1)下载并安装启动器
echo  (2) 注册账户并登录，实名认证 （Sakurafrp与本程序无任何关系 仅用于内网穿透）
echo  (3) 页面顶栏点击  首页  ，每日签到获取流量
echo  (4) 页面顶栏点击  用户  ，右下部分账号信息 -> 访问密钥 -> 点击复制
echo.
echo.
echo.
start "" "https://www.natfrp.com/tunnel/download"
pause

echo.
echo ================================================
echo		[2/4] SakuraFrp启动器配置
echo ================================================
echo.
echo  (1) 打开SakuraFrp启动器，最左侧点击  设置
echo. (2) 在账户 -> 访问密钥 粘贴上一步复制的 访问密钥 ，登录
echo  (3) 点击顶部加号 进入 创建隧道界面 随便选一个节点
echo  (4) 填写以下信息:
echo      -------------------------------------------------
echo      ^| #67 xx电信PLUS               ^|  TCP隧道        ^|
echo      ^| 隧道名  任意名称             ^|  备注           ^|
echo      ^| 本地 IP  本地主机(127.0.0.1) ^|  本地端口  8080 ^|
echo      ^| HTTPS 模式            自动   ^|
echo      ^| 访问密码      (留空，不填)   ^|
echo      -------------------------------------------------
echo.
echo   其他选项不用改，直接点"创建"。
echo.
echo.
echo.
pause

echo.
echo ================================================
echo		[3/4] 开启隧道
echo ================================================
echo.
echo   创建完成后，点"开启隧道"。
echo.
echo   启动成功后，日志里会显示类似这样的地址:
echo.
echo      TCP 隧道启动成功
echo      使用 ^>^>  xxx.natfrp.com:12345  连接你的隧道
echo.
echo   把地址记下来！
echo.
echo.
echo.
pause

echo.
echo ================================================
echo		[4/4] 启动 Gateway + 手机连接
echo ================================================
echo.
echo   现在你的隧道已经通了。
echo.
echo   回到 Gateway 目录，双击 run.bat 启动服务。
echo.
echo   然后手机浏览器打开:
echo.
echo         https://xxx.natfrp.com:12345
echo	（ 前面加上https:// ）
echo   输入你设置的密钥，就可以开始用了！
echo.
echo.
echo.
echo   提示:
echo   - 每日签到可获取内网穿透流量
echo   - 之后仅需运行run.bat即可正常使用
echo   - 不用每次都重新创建
echo.
echo.
echo.
pause


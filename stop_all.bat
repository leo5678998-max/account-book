@echo off
chcp 65001 >nul
title 停止記帳系統與隧道

echo 正在關閉記帳系統與 Cloudflare 隧道進程...
taskkill /F /IM cloudflared.exe >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq Account Book Backend Service*" >nul 2>&1

echo 服務已全數停止！
timeout /t 2 >nul


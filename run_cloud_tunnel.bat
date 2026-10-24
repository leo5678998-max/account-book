@echo off
chcp 65001 >nul
title 雲端外網通道 - 理財記帳系統 (Cloudflare Tunnel)

echo =====================================================================
echo   理財記帳系統 + Cloudflare Tunnel 免費雲端外網通道啟動中
echo =====================================================================
echo.
echo [1/2] 啟動後端伺服器 (http://127.0.0.1:8000)...
start "Account Book Backend Service" /min cmd /c "backend\venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000"

echo [2/2] 正在向 Cloudflare 申請安全加密隧道...
echo.
echo ---------------------------------------------------------------------
echo  請注意看下方終端機輸出：
echo  找到類似 【 https://xxxx-xxxx-xxxx.trycloudflare.com 】 的網址
echo  複製該網址，即可在【手機 4G/5G】或【任何外網電腦】隨時隨地開啟記帳！
echo.
echo  電腦本地也可直接點開： http://localhost:8000
echo ---------------------------------------------------------------------
echo.

tools\cloudflared.exe tunnel --url http://127.0.0.1:8000
pause


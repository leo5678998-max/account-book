@echo off
chcp 65001 >nul
title 理財記帳系統 (ngrok 固定網址)
cd /d "%~dp0"

echo =====================================================================
echo   理財記帳系統 + ngrok 永久固定網址啟動中
echo =====================================================================
echo.

echo [*] 清理先前殘留進程...
taskkill /F /IM ngrok.exe >nul 2>&1
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do taskkill /f /pid %%a >nul 2>&1
timeout /t 1 >nul

echo [1/3] 啟動後端伺服器 (http://localhost:8000)...
start "Account Book Backend Service" /min cmd /c "cd /d "%~dp0backend" && .\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

timeout /t 3 >nul

echo [2/3] 自動開啟本機瀏覽器...
start http://localhost:8000

echo [3/3] 正在連接 ngrok 固定外網隧道...
echo.
echo ---------------------------------------------------------------------
echo  固定公網網址： https://problem-various-marshland.ngrok-free.dev
echo.
echo  【手機/外網連線重要說明】：
echo  首次在手機瀏覽器開啟若出現 ngrok 藍色英文畫面 (ERR_NGROK_6024)，
echo  這是免費版防偽機制的正常提示！
echo  請直接點擊中間藍色的 【Visit Site】（前往網站） 按鈕即可正常進入！
echo  （點擊一次後手機即會記住 Cookie，後續開啟不再提示）
echo.
echo  【iOS 捷徑 Webhook 設定】：
echo  網址填寫： https://problem-various-marshland.ngrok-free.dev/api/webhook/apple-pay?token=...
echo  標頭 (Headers) 務必加入：
echo    ngrok-skip-browser-warning : 1
echo.
echo  電腦本地瀏覽： http://localhost:8000
echo ---------------------------------------------------------------------
echo.

tools\ngrok.exe http 8000 --url https://problem-various-marshland.ngrok-free.dev
pause

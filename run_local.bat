@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title 智能記帳系統 (本地服務)
cd /d "%~dp0backend"
echo =====================================================================
echo   智能記帳與 AI 單據辨識系統啟動中...
echo   網址: http://localhost:8000
echo =====================================================================
echo.
echo 正在開啟瀏覽器...
start http://localhost:8000
.\venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause

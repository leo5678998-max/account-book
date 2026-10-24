[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
Set-Location $PSScriptRoot
Write-Host "正在啟動記帳與自動扣款系統 (http://localhost:8000)..." -ForegroundColor Cyan
& ".\venv\Scripts\python.exe" -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload


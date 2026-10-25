# 英雄記帳

這是一套專門為個人財務自動化打造的 Web App，具備以下核心能力：
1. **多帳戶存款管理**：獨立記錄各家銀行（台新、玉山、國泰、星展...）活存、現金與信用卡資產。
2. **🤖 AI 智慧單據辨識 (Gemini 多模態 API)**：
   * 支援**各家銀行信用卡帳單**（國泰、星展、中信、玉山、台新、富邦...）與**公司薪資單**。
   * 支援 **PDF 電子帳單、紙本帳單拍照截圖 (JPG/PNG)**。
   * 自動分類單據、擷取金額與繳款/發薪日，並提供**即時預覽確認與手動修正**。
   * 上傳薪資單自動套用每月實領月薪設定，並可一鍵計入活存入帳！
3. **線上帳單編輯與補登**：支援對帳單直接進行「修改金額與扣款日」或「刪除錯誤帳單」，徹底避免辨識誤差。
4. **自動撈取 Gmail 電子帳單**：透過 Gmail API 定時搜尋星展銀行的信用卡電子帳單。
5. **排程自動扣款**：內建 APScheduler 排程引擎，於扣繳日當天自動從指定存款帳戶扣除卡費並留下流水帳記錄。

---

## 快速預覽架構

* **後端**：Python (FastAPI + SQLAlchemy + SQLite + google-genai + pypdf + APScheduler + Google API Client)
* **前端**：響應式 SPA 現代儀表板（Tailwind CSS + Vue 3 + Chart.js + Lucide Icons，內嵌託管，免裝 Node.js）
* **AI 辨識**：Google Gemini 3.8 Flash (支援 PDF / 圖片視覺辨識，個人使用完全免費)
* **資料庫**：SQLite（檔案持久化儲存，備份簡單）
* **部屬**：Docker + Docker Compose

---

## 一、 Google Gemini API 免費 Key 申請指南 (推薦)

為了啟用 AI 辨識各家銀行帳單與薪資單：
1. 前往 [Google AI Studio](https://aistudio.google.com/) 登入您的 Google 帳號。
2. 點擊「**Get API Key**」>「**Create API Key**」。
3. 複製取得的 API Key。
4. 進入記帳系統網頁，點擊右上角「⚙️ 系統設定」，貼入 **Google Gemini API Key** 並儲存即可！（個人使用每日 1,500 次完全免費）。

---

## 二、 Google Cloud Console 設定指南 (Gmail 自動抓取帳單)

若需要啟用定時從 Gmail 自動抓取星展銀行電子帳單：
1. 前往 [Google Cloud Console](https://console.cloud.google.com/)。
2. 建立新專案並啟用 **Gmail API**。
3. 設定 OAuth 同意畫面（外部），新增您的 Gmail 為測試使用者。
4. 建立「OAuth 用戶端 ID」（網頁應用程式），設定 Redirect URI 為 `http://localhost:8000/api/auth/google/callback`。
5. 在記帳系統設定中填入 Client ID 與 Client Secret 並完成授權。

---

## 三、 本地環境啟動

```bash
cd backend

# Windows:
run.bat

# 或手動啟動:
.\venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
打開瀏覽器訪問 `http://localhost:8000` 即可使用。

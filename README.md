# 智能記帳 & 星展銀行信用卡 Gmail 自動扣款系統

這是一套專門為個人財務自動化打造的 Web App，具備以下核心能力：
1. **多帳戶存款管理**：獨立記錄各家銀行（台新、玉山、國泰...）活存、現金與信用卡資產。
2. **自動撈取 Gmail 電子帳單**：透過 Gmail API 定時搜尋星展銀行的信用卡電子帳單。
3. **加密 PDF 解析引擎**：使用 Python 在記憶體中解密星展銀行的加密 PDF，自動提取「本期應繳總額」與「繳款截止日 / 自動扣繳日」。
4. **定時自動扣款**：內建 APScheduler 排程引擎，於扣繳日當天自動從指定存款帳戶扣除卡費並留下流水帳記錄。

---

## 快速預覽架構

* **後端**：Python (FastAPI + SQLAlchemy + SQLite + pypdf + APScheduler + Google API Client)
* **前端**：響應式 SPA 現代儀表板（Tailwind CSS + Vue 3 + Lucide Icons，內嵌託管，免裝 Node.js）
* **資料庫**：SQLite（檔案持久化儲存，備份簡單）
* **部屬**：Docker + Docker Compose

---

## 一、 Google Cloud Console 設定指南 (取得 Gmail API 權限)

為了讓系統能自動搜尋讀取您的星展銀行電子帳單，需要建立一組 Google OAuth 2.0 憑證：

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)。
2. 點擊頂部建立一個新專案（例如：`MyAccountBook`）。
3. **啟用 Gmail API**：
   * 進入「API 和服務」>「已啟用的 API 和服務」>「+ 啟用 API 和服務」。
   * 搜尋 `Gmail API` 並點擊「啟用」。
4. **設定 OAuth 同意畫面**：
   * 進入「API 和服務」>「OAuth 同意畫面」。
   * 使用者類型選擇「外部 (External)」，點擊「建立」。
   * 填寫應用程式名稱（如 `Personal Finance`）與您的開發者電子郵件。
   * 在「測試使用者 (Test Users)」清單中，**新增您自己的 Gmail 地址**。
5. **建立 OAuth 2.0 Client ID**：
   * 進入「API 和服務」>「憑證」>「+ 建立憑證」> 選擇「OAuth 用戶端 ID」。
   * 應用程式類型選擇「**網頁應用程式 (Web application)**」。
   * **已授權的重新導向 URI (Authorized redirect URIs)** 填入：
     * 本地測試：`http://localhost:8000/api/auth/google/callback`
     * 雲端伺服器：`http://<您的伺服器IP或網域>:8000/api/auth/google/callback`
   * 點擊「建立」後，複製取得的 **用戶端 ID (Client ID)** 與 **用戶端密碼 (Client Secret)**。

---

## 二、 雲端伺服器 (VPS / Linux) 一鍵部署

在雲端伺服器上（已安裝 Docker 與 Docker Compose）：

1. 將本專案上傳至伺服器：
   ```bash
   git clone <您的專案庫> account-book
   cd account-book
   ```
2. 啟動服務：
   ```bash
   docker compose up -d --build
   ```
3. 打開瀏覽器訪問：
   `http://<您的伺服器IP>:8000`

---

## 三、 本地環境直接運行 (Python)

若想先在自己的電腦測試運行：

1. 建立並啟用 Python 虛擬環境：
   ```bash
   cd backend
   python -m venv venv
   
   # Windows PowerShell:
   .\venv\Scripts\Activate.ps1
   # macOS / Linux:
   source venv/bin/activate
   ```
2. 安裝後端相依套件：
   ```bash
   pip install -r requirements.txt
   ```
3. 啟動伺服器：
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
4. 打開瀏覽器訪問 `http://localhost:8000` 即可進入系統。

---

## 四、 系統初次設定與使用流程

1. **新增存款帳戶**：
   * 點擊「新增帳戶」，例如新增「台新 Richart 活存」、「玉山銀行存款」等，並勾選「設為星展銀行信用卡預設扣款帳戶」。
2. **設定星展帳單密碼與 Gmail 連線**：
   * 點擊右上角「⚙️ 系統設定」。
   * 輸入星展銀行 PDF 帳單的解密密碼（星展銀行預設為：身分證字號首字母大寫 + 生日）。
   * 輸入 Google Client ID 與 Client Secret，點擊「前往 Google 授權此 App 讀取 Gmail」。
   * 授權完成後，系統會自動在背景取得 Refresh Token，日後雲端自動巡檢完全不需重複登入！
3. **帳單抓取與自動扣款規則**：
   * **自動排程**：系統內建排程服務，**每天凌晨 03:00** 會自動：
     1. 檢查 Gmail 搜尋星展銀行新帳單附件 PDF。
     2. 在記憶體中解密並提取應繳金額與到期日，建立待扣款帳單。
     3. 檢驗當天到期的待扣款帳單，自動從扣款帳戶餘額扣除並新增一筆支出明細。
   * **手動功能**：
     * 點擊「同步 Gmail」隨時立即抓取最新信件。
     * 點擊「上傳帳單」可直接上傳手邊的 PDF 測試解密與解析成果。
     * 點擊「手動扣款」可隨時立即執行扣款。


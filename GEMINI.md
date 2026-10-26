# 專案重構與程式碼開發規範 (Development & Refactoring Guidelines)

本專案的所有代碼修改、新增與重構工作，必須嚴格遵守以下準則：

---

## 1. 核心開發與重構原則

- **保持可編譯與可運行 (Maintain Buildability)**：
  - 每一個重構或修改步驟結束時，整個專案都必須維持在隨時可以正常編譯、建置與執行的完整狀態。
  - 嚴格禁止產生需要跨多個步驟才能修復的半成品代碼。

- **最小改動原則 (Minimal Diff)**：
  - 非必要不重構。只針對目標模組的架構結構進行最佳化，避免更動已穩定運行的底層邏輯或演算法細節。

- **單一職責原則 (Single Responsibility Principle, SRP)**：
  - 拆分過於龐大或職責混雜的函式，確保每個函式專注於單一任務。

- **消除硬編碼 (Extract Constants / Magic Values)**：
  - 嚴禁在業務邏輯中散落魔法數字或魔法字串（如交易類型、帳單狀態、分類名稱等）。
  - 所有固定值均須提取成領域常數（Domain Constants）或設定檔。

- **商業邏輯與資料存取解耦 (Decouple Business Logic & Data Access)**：
  - 將純數值運算、規則判斷等核心邏輯與資料庫 Session（SQLAlchemy）、I/O 存取與介面層抽離，便於純單元測試。

- **保持 Public API 介面向下相容 (API Backward Compatibility)**：
  - 既有的公開函式簽章（Function Signature）、參數名稱與回傳型別必須保持不變，避免破壞現有呼叫端相容性。

- **Dead Code 處理原則 (Annotate Dead Code)**：
  - 若重構過程中發現未使用的死代碼（Dead Code）或舊版歷史相容分支，**嚴禁直接刪除**。
  - 必須以註解明確標註 `[相容保留 / 潛在 Dead Code]`，並向使用者提出說明。

---

## 2. 驗證機制與回報規範

- **主動執行測試與驗證 (Verification)**：
  - 每次代碼修改完畢後，必須主動執行專案中的單元測試套件（如 `backend/tests/`）與 FastAPI 主應用啟動檢測，確保測試全數通過（Zero Errors）。

- **改動說明與呼叫示範 (Explanations & Usage)**：
  - 每次修改完成後，均須說明改動原因、架構效益以及外部呼叫方式。

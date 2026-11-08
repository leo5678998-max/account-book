import os
import json
import io
import re
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from google import genai
from google.genai import types
from ..stock_service import get_currency_rate_to_twd

def get_password_candidates(passwords: Optional[Union[str, List[str]]]) -> List[str]:
    """根據輸入的密碼清單或字串，自動衍生全大寫、全小寫等候選密碼清單以適應不同銀行"""
    if not passwords:
        return []
    if isinstance(passwords, str):
        raw_list = [passwords]
    else:
        raw_list = passwords

    candidates = []
    for p in raw_list:
        if not p or not isinstance(p, str):
            continue
        p = p.strip()
        if not p:
            continue
        for variant in [p, p.upper(), p.lower()]:
            if variant not in candidates:
                candidates.append(variant)
    return candidates

def extract_pdf_first_pages_text(pdf_bytes: bytes, password: Optional[Union[str, List[str]]] = None, max_pages: int = 3) -> str:
    """嘗試從 PDF 抽取前幾頁的純文字，若有密碼則嘗試解密"""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted:
            candidates = get_password_candidates(password)
            decrypted = False
            for pwd in candidates:
                try:
                    if reader.decrypt(pwd):
                        decrypted = True
                        break
                except Exception:
                    continue
            if not decrypted:
                return ""

        text = ""
        for i in range(min(len(reader.pages), max_pages)):
            extracted = reader.pages[i].extract_text()
            if extracted:
                text += f"\n--- Page {i+1} ---\n" + extracted
        return text
    except Exception:
        return ""

def decrypt_pdf_if_needed(pdf_bytes: bytes, password: Optional[Union[str, List[str]]] = None) -> bytes:
    """若 PDF 加密且提供密碼，嘗試候選密碼解密後輸出普通 PDF bytes"""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted and password:
            candidates = get_password_candidates(password)
            for pwd in candidates:
                try:
                    res = reader.decrypt(pwd)
                    if res:
                        from pypdf import PdfWriter
                        writer = PdfWriter()
                        for page in reader.pages:
                            writer.add_page(page)
                        out = io.BytesIO()
                        writer.write(out)
                        return out.getvalue()
                except Exception:
                    continue
    except Exception:
        pass
    return pdf_bytes

def parse_document_with_gemini(
    file_bytes: bytes,
    filename: str,
    api_key: str,
    password: Optional[Union[str, List[str]]] = None
) -> Dict[str, Any]:
    """
    使用 Google Gemini 多模態 API 解析單據
    支援：國泰世華、中國信託、玉山銀行、台新銀行、台北富邦、星展銀行等各家信用卡帳單與公司薪資單
    """
    if not api_key:
        return {"success": False, "error": "尚未設定 GEMINI_API_KEY"}

    client = genai.Client(api_key=api_key)
    lower_name = filename.lower()
    
    extracted_text = ""
    is_pdf = lower_name.endswith(".pdf")
    
    if is_pdf:
        # 若為 PDF 先嘗試解密與提取文字
        clean_bytes = decrypt_pdf_if_needed(file_bytes, password)
        try:
            chk_reader = PdfReader(io.BytesIO(clean_bytes))
            if chk_reader.is_encrypted:
                return {
                    "success": False,
                    "error": "此 PDF 帳單設有密碼保護，且您提供的解密密碼（身分證字號或專屬密碼）無法解鎖。請確認密碼是否正確。"
                }
        except Exception:
            pass
        extracted_text = extract_pdf_first_pages_text(clean_bytes, None, max_pages=3)
        mime_type = "application/pdf"
    elif lower_name.endswith((".jpg", ".jpeg")):
        mime_type = "image/jpeg"
        clean_bytes = file_bytes
    elif lower_name.endswith(".png"):
        mime_type = "image/png"
        clean_bytes = file_bytes
    elif lower_name.endswith(".webp"):
        mime_type = "image/webp"
        clean_bytes = file_bytes
    else:
        mime_type = "application/octet-stream"
        clean_bytes = file_bytes

    prompt_instruction = """
你是一位專業的個人財務與會計 AI 助手。請分析這份金融單據（可能是信用卡帳單、日常消費發票/收據、超商/餐廳結帳明細、海外購物 Invoice，或是公司薪資明細單）。
請自動辨識單據類型、幣別並精確擷取關鍵欄位，以純 JSON 格式輸出：

1. document_type:
   - "CREDIT_CARD_BILL": 銀行信用卡月結單 (需於未來截止日繳費或自動扣繳之帳單)
   - "EXPENSE_RECEIPT": 日常消費發票、超商/超市明細、餐廳收據、交通車資、海外購物 Invoice (已完成結帳之各筆支出單據)
   - "SALARY_SLIP": 公司薪資單 / 薪資明細 / 薪水條
   - "UNKNOWN": 無法辨認之其他單據

2. bank_or_company: 
   - 信用卡請填寫發卡機構名稱（例如「國泰世華銀行」、「星展銀行」等）。
   - 消費發票/收據請填寫商家或機構名稱（例如「7-ELEVEN」、「全聯」、「星巴克」、「Uber」、「Amazon」、「麥當勞」等）。
   - 薪資單請填寫發薪公司名稱。

3. category: 最適合的財務分類，請從以下標準分類中擇一：
   "飲食", "交通", "購物", "日用品", "娛樂", "居住", "電信網路", "醫療", "保險", "信用卡費", "薪資收入", "其他"

4. description: 簡明扼要之消費說明（例如「全聯 採買生鮮」、「星巴克 咖啡消費」、「Uber 搭車」、「7-ELEVEN 門市消費」）。

5. currency: 幣別代碼，例如 "TWD" (新台幣)、"USD" (美元)、"JPY" (日圓)、"EUR" (歐元)、"CNY" (人民幣)、"HKD" (港幣)、"GBP" (英鎊)、"KRW" (韓元)。台灣本土發票/帳單預設為 "TWD"；若為海外單據請準確識別外幣代碼。

6. original_amount: 原始票面總金額 (float 數值，去掉千分位逗號)。若為外幣請填寫該外幣之原始票面金額；若為台幣單據則與 total_amount 相同。

7. total_amount: 
   - 若為信用卡帳單：請填寫「本期應繳總額 / 應付總額 / 新增應繳款 / 自動扣繳金額」，數值 float，去掉千分位逗號。
   - 若為消費發票/收據：請填寫「結帳總金額 / 總計 / 實付金額」，數值 float。
   - 若為薪資單：請填寫「實領薪資 / 實發金額 / 淨發金額」（非應發總額，而是實際入帳之淨額）。

8. statement_month: 所屬月份，格式為 "YYYY-MM"（例如 "2026-10"）。若年份為民國年請換算為西元年（民國115年為2026年）。

9. minimum_amount: 最低應繳金額 (數值 float)。信用卡帳單若有請填寫，發票/薪資單填 0.0。

10. due_date: 格式為 "YYYY-MM-DD"。
    - 信用卡帳單：繳款截止日 / 最後繳款日 / 自動扣款日。
    - 發票/收據：開立日期 / 交易日期。
    - 薪資單：發薪日期 / 入帳日。

11. statement_date: 格式為 "YYYY-MM-DD"。單據開立日或帳單結帳日。

12. confidence_summary: 簡述辨識成果，說明商家/機構、單據類型、幣別、金額與日期。

請務必只輸出合法的 JSON 字串。
"""

    # 候選模型順序：優先使用快速穩定的 3.5-flash-lite，其次嘗試 3.8-flash，再次 3.1-flash-lite
    candidate_models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
    last_error = ""

    for model_name in candidate_models:
        try:
            # 若為 PDF 且已提取出文字，直接傳遞文字效果最佳且不會觸發 503
            if is_pdf and len(extracted_text.strip()) > 50:
                full_content = f"{prompt_instruction}\n\n單據文字內容如下：\n{extracted_text}"
                response = client.models.generate_content(
                    model=model_name,
                    contents=full_content,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
            else:
                # 純圖片或無法提取文字的掃描件，使用多模態 Part 傳入
                file_part = types.Part.from_bytes(data=clean_bytes, mime_type=mime_type)
                response = client.models.generate_content(
                    model=model_name,
                    contents=[file_part, prompt_instruction],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )

            text_resp = response.text
            if not text_resp:
                continue

            cleaned_json = text_resp.strip()
            if cleaned_json.startswith("```"):
                cleaned_json = re.sub(r'^```(?:json)?\s*', '', cleaned_json)
                cleaned_json = re.sub(r'\s*```$', '', cleaned_json)

            data = json.loads(cleaned_json)
            data["success"] = True

            # 處理外幣 (USD / JPY / EUR 等) 自動換算為新台幣
            raw_currency = str(data.get("currency", "TWD")).strip().upper()
            if raw_currency in ("NTD", "NT$", "NT", "$", "元", "", "NONE", "NULL"):
                raw_currency = "TWD"

            raw_orig_amt = data.get("original_amount") or data.get("total_amount") or 0.0
            try:
                orig_amount = float(raw_orig_amt)
            except (ValueError, TypeError):
                orig_amount = 0.0

            data["currency"] = raw_currency
            data["original_amount"] = orig_amount

            if raw_currency != "TWD" and orig_amount > 0:
                rate = get_currency_rate_to_twd(raw_currency)
                data["exchange_rate"] = rate
                converted_twd = round(orig_amount * rate)
                data["total_amount"] = float(converted_twd)

                conversion_note = f"【外幣自動換算】原幣 {raw_currency} {orig_amount:,.2f} × 即時匯率 {rate} ＝ 折合 NT$ {converted_twd:,.0f}"
                orig_summary = data.get("confidence_summary", "")
                data["confidence_summary"] = f"{conversion_note}。{orig_summary}" if orig_summary else conversion_note
                data["notes"] = conversion_note
            else:
                data["exchange_rate"] = 1.0
                if "total_amount" in data:
                    try:
                        data["total_amount"] = float(data["total_amount"])
                    except (ValueError, TypeError):
                        data["total_amount"] = orig_amount

            return data

        except Exception as e:
            last_error = str(e)
            print(f"[AI Parser] 模型 {model_name} 呼叫失敗: {last_error}，嘗試下一個備用模型...")
            continue

    return {"success": False, "error": f"Gemini 辨識發生錯誤: {last_error}"}

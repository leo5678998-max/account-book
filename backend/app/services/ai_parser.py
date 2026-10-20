import os
import json
import io
import re
from typing import Dict, Any, Optional
from datetime import datetime
from pypdf import PdfReader
from google import genai
from google.genai import types

def extract_pdf_first_pages_text(pdf_bytes: bytes, password: Optional[str] = None, max_pages: int = 3) -> str:
    """嘗試從 PDF 抽取前幾頁的純文字，若有密碼則解密"""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted:
            if password:
                reader.decrypt(password)
            else:
                return ""
        text = ""
        for i in range(min(len(reader.pages), max_pages)):
            extracted = reader.pages[i].extract_text()
            if extracted:
                text += f"\n--- Page {i+1} ---\n" + extracted
        return text
    except Exception:
        return ""

def decrypt_pdf_if_needed(pdf_bytes: bytes, password: Optional[str] = None) -> bytes:
    """若 PDF 加密且提供密碼，解密後輸出解密後的 PDF bytes"""
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted and password:
            res = reader.decrypt(password)
            if res:
                from pypdf import PdfWriter
                writer = PdfWriter()
                for page in reader.pages:
                    writer.add_page(page)
                out = io.BytesIO()
                writer.write(out)
                return out.getvalue()
    except Exception:
        pass
    return pdf_bytes

def parse_document_with_gemini(
    file_bytes: bytes,
    filename: str,
    api_key: str,
    password: Optional[str] = None
) -> Dict[str, Any]:
    """
    使用 Google Gemini 多模態 API 解析單據（支援多家銀行信用卡帳單、薪資單、PDF/圖片）
    """
    if not api_key:
        return {"success": False, "error": "尚未設定 GEMINI_API_KEY"}

    client = genai.Client(api_key=api_key)
    lower_name = filename.lower()
    
    extracted_text = ""
    is_pdf = lower_name.endswith(".pdf")
    
    if is_pdf:
        # 若為 PDF 先嘗試提取文字
        extracted_text = extract_pdf_first_pages_text(file_bytes, password, max_pages=3)
        clean_bytes = decrypt_pdf_if_needed(file_bytes, password)
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
你是一位專業的個人財務與會計 AI 助手。請分析此份單據文件（可能是信用卡電子帳單、紙本帳單拍照、或公司薪資單明細）。
請自動辨識單據類型並精確擷取關鍵欄位，以純 JSON 格式輸出：

1. document_type:
   - "CREDIT_CARD_BILL": 信用卡帳單（如星展、國泰、玉山、中信、台新、富邦、聯邦等任何銀行）
   - "SALARY_SLIP": 薪資單 / 薪資明細 / 薪水條
   - "UNKNOWN": 無法辨認之其他單據

2. bank_or_company: 銀行名稱（例如「星展銀行」、「國泰世華商業銀行」、「中國信託」）或 發薪公司名稱。

3. statement_month: 所屬月份，格式為 "YYYY-MM"（例如 "2026-09"）。請依據帳單上標明的帳單月份（若為民國年請換算為西元年）。

4. total_amount: 
   - 若為信用卡帳單：請填寫「本期應繳總額 / 本期應付總額 / 自動扣繳金額」，必須是數值 float，去掉千分位逗號。若有特別標明「將自動扣繳 XXX 元」，請以此為應繳總額。
   - 若為薪資單：請填寫「實領薪資 / 實發金額 / 淨發金額」（非應發總額，而是實際入帳之淨額）。

5. minimum_amount: 
   - 若為信用卡帳單：最低應繳金額 (數值 float)。若無則填 0.0。
   - 若為薪資單：可填 0.0。

6. due_date: 格式為 "YYYY-MM-DD"
   - 若為信用卡帳單：繳款截止日 / 最後繳款日 / 自動扣繳日。
   - 若為薪資單：發薪日期 / 入帳日。

7. statement_date: 格式為 "YYYY-MM-DD"
   - 帳單結帳日 / 計算基準日。若無則為 null。

8. confidence_summary: 簡述辨識成果，說明發卡銀行/公司、帳單月份、應繳/實領金額與截止日。

請務必只輸出合法的 JSON 字串。
"""

    # 候選模型順序：優先使用快速穩定的 3.5-flash-lite，其次嘗試 3.8-flash，再次 3.1-flash-lite
    candidate_models = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.1-flash-lite"]
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
            return data

        except Exception as e:
            last_error = str(e)
            print(f"[AI Parser] 模型 {model_name} 呼叫失敗: {last_error}，嘗試下一個備用模型...")
            continue

    return {"success": False, "error": f"Gemini 辨識發生錯誤: {last_error}"}

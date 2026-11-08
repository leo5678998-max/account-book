# [相容保留 / 潛在 Dead Code]
# 本模組為舊版星展銀行本地 PDF 正規表達式解析器。
# 系統單據辨識現已全面改由純 Google Gemini 多模態 AI (ai_parser.py) 辨識處理，支援各家銀行與各類發票。
# 依照專案規範 GEMINI.md 保留此歷史相容模組。

import re
import io
from datetime import datetime, date
from typing import Optional, Dict, Any
from pypdf import PdfReader
from pypdf.errors import PdfReadError

def normalize_date(date_str: str) -> Optional[date]:
    """將民國年或西元年字串標準化為 python date 物件"""
    if not date_str:
        return None
    date_str = date_str.strip()
    
    # 格式 1: 西元年 2026/10/25 或 2026-10-25
    ad_match = re.match(r'(\d{4})\s*[年/.-]\s*(\d{1,2})\s*[月/.-]\s*(\d{1,2})\s*日?', date_str)
    if ad_match:
        year = int(ad_match.group(1))
        month = int(ad_match.group(2))
        day = int(ad_match.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None

    # 格式 2: 民國年 115/10/25 或 115年10月25日
    roc_match = re.match(r'(\d{2,3})\s*[年/.-]\s*(\d{1,2})\s*[月/.-]\s*(\d{1,2})\s*日?', date_str)
    if roc_match:
        year = int(roc_match.group(1))
        if year < 1900:
            year += 1911
        month = int(roc_match.group(2))
        day = int(roc_match.group(3))
        try:
            return date(year, month, day)
        except ValueError:
            return None

    return None

def clean_amount(amount_str: str) -> float:
    """清理金額字串，移除 NT$, $, 逗號，轉為 float"""
    if not amount_str:
        return 0.0
    cleaned = re.sub(r'[^\d.-]', '', amount_str)
    try:
        val = float(cleaned)
        # 防呆：如果誤匹配到年份 (例如 2026, 2027 等且帶有 / 格式)，可過濾
        return val
    except ValueError:
        return 0.0

def parse_dbs_pdf(pdf_stream_or_bytes: bytes, password: str) -> Dict[str, Any]:
    """
    解密並解析星展銀行 (DBS) 信用卡 PDF 電子帳單
    """
    try:
        pdf_file = io.BytesIO(pdf_stream_or_bytes)
        reader = PdfReader(pdf_file)
    except Exception as e:
        return {"success": False, "error": f"無法讀取 PDF 檔案: {str(e)}"}

    # 檢查是否加密
    if reader.is_encrypted:
        try:
            res = reader.decrypt(password)
            if not res:
                return {"success": False, "error": "PDF 密碼錯誤，解密失敗"}
        except Exception as e:
            return {"success": False, "error": f"解密過程發生錯誤: {str(e)}"}

    # 抽取前 3 頁文字
    full_text = ""
    try:
        pages_to_read = min(len(reader.pages), 3)
        for i in range(pages_to_read):
            text = reader.pages[i].extract_text()
            if text:
                full_text += f"\n--- Page {i+1} ---\n" + text
    except Exception as e:
        return {"success": False, "error": f"提取 PDF 文字失敗: {str(e)}"}

    if not full_text.strip():
        return {"success": False, "error": "PDF 為掃描圖片或無法提取純文字"}

    total_amount = 0.0
    minimum_amount = 0.0
    due_date = None
    statement_date = None
    statement_month = None

    # ====== 優先比對：星展銀行特徵排版 ======
    # 1. 帳單月份：例如「2026年09月信用卡帳單」
    month_match = re.search(r'(\d{4})\s*年\s*(\d{1,2})\s*月信用卡帳單', full_text)
    if month_match:
        y = month_match.group(1)
        m = int(month_match.group(2))
        statement_month = f"{y}-{m:02d}"

    # 2. 自動扣繳金額提示：例如「將自動扣繳15,486元」
    auto_debit_match = re.search(r'將?自動扣繳\s*([0-9,]+(?:\.[0-9]{2})?)\s*元', full_text)
    if auto_debit_match:
        total_amount = clean_amount(auto_debit_match.group(1))

    # 3. 帳務明細兩大日期：結帳日 繳款截止日 (例如 2026/09/16 2026/10/05)
    dates_row_match = re.search(r'帳務明細[^\n]*\n\s*(\d{4}/\d{1,2}/\d{1,2})\s+(\d{4}/\d{1,2}/\d{1,2})', full_text)
    if dates_row_match:
        statement_date = normalize_date(dates_row_match.group(1))
        due_date = normalize_date(dates_row_match.group(2))

    # 4. 金額列解析：13,165 13,165 15,486 15,486 1,560 (上期結餘、已付、應繳、應繳、最低)
    if total_amount == 0.0:
        amt_row_match = re.search(r'\n([0-9,]+)\s+([0-9,]+)\s+([0-9,]+)\s+([0-9,]+)\s+([0-9,]+)', full_text)
        if amt_row_match:
            total_amount = clean_amount(amt_row_match.group(3))
            minimum_amount = clean_amount(amt_row_match.group(5))
    else:
        # 若已從自動扣繳文字抓到總額，從數值行提取最低應繳
        amt_row_match = re.search(r'\n[0-9,]+\s+[0-9,]+\s+[0-9,]+\s+[0-9,]+\s+([0-9,]+)', full_text)
        if amt_row_match:
            minimum_amount = clean_amount(amt_row_match.group(1))

    # ====== 通用正則補救 (Fallback) ======
    if total_amount == 0.0:
        amount_patterns = [
            r'(?:本\s*期\s*應\s*(?:繳|付)\s*(?:款\s*)?總\s*額|應\s*(?:繳|付)\s*總\s*額|本\s*期\s*結\s*算\s*金\s*額)[^\dNT$]*?(?:NT\$|\$)?\s*([0-9,]+(?:\.[0-9]{2})?)',
            r'(?:New\s*Balance|Total\s*Amount\s*Due)[^\dNT$]*?(?:NT\$|\$)?\s*([0-9,]+(?:\.[0-9]{2})?)',
        ]
        for pattern in amount_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                total_amount = clean_amount(match.group(1))
                break

    if due_date is None:
        due_patterns = [
            r'(?:繳\s*款\s*截\s*止\s*日|最\s*後\s*繳\s*款\s*日|自\s*動\s*扣\s*繳\s*日)[^\d民國]*?((?:\d{2,4}\s*[年/.-]\s*\d{1,2}\s*[月/.-]\s*\d{1,2}\s*日?))',
            r'(?:Payment\s*Due\s*Date)[^\d]*?((?:\d{2,4}\s*[年/.-]\s*\d{1,2}\s*[月/.-]\s*\d{1,2}\s*日?))',
        ]
        for pattern in due_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                due_date = normalize_date(match.group(1))
                if due_date:
                    break

    if statement_month is None:
        if statement_date:
            statement_month = statement_date.strftime("%Y-%m")
        elif due_date:
            statement_month = due_date.strftime("%Y-%m")

    # 防呆檢驗
    is_explicit_zero = bool(re.search(r'(?:無須繳款|毋須繳款|本期結餘為\s*0)', full_text))
    needs_review = (total_amount == 0.0 and not is_explicit_zero)

    return {
        "success": True,
        "bank_name": "星展銀行",
        "statement_date": statement_date,
        "statement_month": statement_month,
        "due_date": due_date,
        "total_amount": total_amount,
        "minimum_amount": minimum_amount,
        "needs_review": needs_review,
        "confidence_summary": f"星展銀行 {statement_month or ''} 帳單，應繳總額 NT$ {total_amount:,.0f}，截止日 {due_date}",
        "raw_snippet": full_text[:400]
    }

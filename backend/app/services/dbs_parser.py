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
    
    # 格式 1: 民國年 115/10/25 或 115年10月25日
    roc_match = re.match(r'(\d{2,3})[年/.-](\d{1,2})[月/.-](\d{1,2})日?', date_str)
    if roc_match:
        year = int(roc_match.group(1))
        # 若是民國年 (通常小於 1900)
        if year < 1900:
            year += 1911
        month = int(roc_match.group(2))
        day = int(roc_match.group(3))
        return date(year, month, day)

    # 格式 2: 西元年 2026/10/25 或 2026-10-25
    ad_match = re.match(r'(\d{4})[年/.-](\d{1,2})[月/.-](\d{1,2})日?', date_str)
    if ad_match:
        year = int(ad_match.group(1))
        month = int(ad_match.group(2))
        day = int(ad_match.group(3))
        return date(year, month, day)

    return None

def clean_amount(amount_str: str) -> float:
    """清理金額字串，移除 NT$, $, 逗號，轉為 float"""
    if not amount_str:
        return 0.0
    cleaned = re.sub(r'[^\d.-]', '', amount_str)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def parse_dbs_pdf(pdf_stream_or_bytes: bytes, password: str) -> Dict[str, Any]:
    """
    解密並解析星展銀行 (DBS) 信用卡 PDF 電子帳單
    
    回傳範例:
    {
        "success": True,
        "bank_name": "星展銀行",
        "statement_date": date(2026, 10, 5),
        "statement_month": "2026-10",
        "due_date": date(2026, 10, 25),
        "total_amount": 15800.0,
        "minimum_amount": 1000.0,
        "raw_text_snippet": "..."
    }
    """
    try:
        pdf_file = io.BytesIO(pdf_stream_or_bytes)
        reader = PdfReader(pdf_file)
    except Exception as e:
        return {"success": False, "error": f"無法讀取 PDF 檔案: {str(e)}"}

    # 檢查是否加密
    if reader.is_encrypted:
        try:
            # pypdf decrypt 回傳 DecryptionResult (0 代表失敗，1 或 2 代表成功)
            res = reader.decrypt(password)
            if not res:
                return {"success": False, "error": "PDF 密碼錯誤，解密失敗"}
        except Exception as e:
            return {"success": False, "error": f"解密過程發生錯誤: {str(e)}"}

    # 抽取前 1~2 頁文字 (主要總覽資訊都在第一或第二頁)
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

    # 正則提取關鍵欄位
    # 1. 本期應繳總額 / 新增應繳款 / 應繳總額
    total_amount = 0.0
    amount_patterns = [
        r'(?:本期應繳總額|本期應繳款總額|應繳總額|本期應付總額)[^\dNT$]*?(?:NT\$|\$)?\s*([0-9,]+(?:\.[0-9]{2})?)',
        r'(?:New Balance|Total Amount Due)[^\dNT$]*?(?:NT\$|\$)?\s*([0-9,]+(?:\.[0-9]{2})?)',
        r'(?:本期結算金額)[^\dNT$]*?(?:NT\$|\$)?\s*([0-9,]+(?:\.[0-9]{2})?)',
    ]
    for pattern in amount_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            total_amount = clean_amount(match.group(1))
            break

    # 2. 繳款截止日 / 自動扣款日
    due_date = None
    due_date_patterns = [
        r'(?:繳款截止日|最後繳款日|自動扣繳日|扣繳日)[^\d民國]*?((?:\d{2,4}[年/.-]\d{1,2}[月/.-]\d{1,2}日?))',
        r'(?:Payment Due Date)[^\d]*?((?:\d{2,4}[年/.-]\d{1,2}[月/.-]\d{1,2}日?))',
        r'截止日[^\d民國]*?((?:\d{2,4}[年/.-]\d{1,2}[月/.-]\d{1,2}日?))',
    ]
    for pattern in due_date_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            due_date = normalize_date(match.group(1))
            if due_date:
                break

    # 3. 帳單結帳日 / 結帳日
    statement_date = None
    statement_patterns = [
        r'(?:帳單結帳日|結帳日|帳單日)[^\d民國]*?((?:\d{2,4}[年/.-]\d{1,2}[月/.-]\d{1,2}日?))',
        r'(?:Statement Date)[^\d]*?((?:\d{2,4}[年/.-]\d{1,2}[月/.-]\d{1,2}日?))',
    ]
    for pattern in statement_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            statement_date = normalize_date(match.group(1))
            if statement_date:
                break

    # 4. 最低應繳金額
    minimum_amount = 0.0
    min_patterns = [
        r'(?:最低應繳金額|最低應繳款|最低繳款金額)[^\dNT$]*?(?:NT\$|\$)?\s*([0-9,]+(?:\.[0-9]{2})?)',
        r'(?:Minimum Payment Due)[^\dNT$]*?(?:NT\$|\$)?\s*([0-9,]+(?:\.[0-9]{2})?)'
    ]
    for pattern in min_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            minimum_amount = clean_amount(match.group(1))
            break

    statement_month = None
    if statement_date:
        statement_month = statement_date.strftime("%Y-%m")
    elif due_date:
        statement_month = due_date.strftime("%Y-%m")

    # 防呆檢驗
    if total_amount == 0.0 and due_date is None:
        return {
            "success": False,
            "error": "未能辨識出應繳金額與截止日，可能是格式變更或排版不同",
            "raw_snippet": full_text[:1000]
        }

    return {
        "success": True,
        "bank_name": "星展銀行",
        "statement_date": statement_date,
        "statement_month": statement_month,
        "due_date": due_date,
        "total_amount": total_amount,
        "minimum_amount": minimum_amount,
        "raw_snippet": full_text[:400]
    }


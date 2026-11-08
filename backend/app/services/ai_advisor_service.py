import os
import re
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from typing import Dict, Any, Optional, List
from sqlalchemy.orm import Session
from fastapi import HTTPException
from google import genai

from ..models import User, Account, Transaction, Bill, RecurringExpense
from ..services.accounting_service import get_setting
from ..services.stock_service import build_portfolio_summary, get_currency_rate_to_twd
from ..services.installment_service import get_installment_summary
from ..services.insurance_service import calculate_insurance_summary


def clean_latex_syntax(text: str) -> str:
    """
    清理 AI 模型可能輸出的 LaTeX 語法標記（如 $$, \\text, \\frac, \\mathbf 等），
    轉換為一般使用者易於閱讀的純文字與易懂數學運算符號。
    """
    if not text:
        return ""
    # 1. 移除雙錢號區塊標記 $$
    cleaned = re.sub(r'\$\$', '', text)
    # 2. 轉義常見符號 \$ -> $, \% -> %
    cleaned = cleaned.replace(r'\$', '$').replace(r'\%', '%')
    # 3. 遞迴去除 \text{...}, \mathbf{...}, \mathit{...}（最多 3 層）
    for _ in range(3):
        cleaned = re.sub(r'\\text\{([^{}]+)\}', r'\1', cleaned)
        cleaned = re.sub(r'\\mathbf\{([^{}]+)\}', r'**\1**', cleaned)
        cleaned = re.sub(r'\\mathit\{([^{}]+)\}', r'*\1*', cleaned)
    # 4. 處理分數 \frac{a}{b} -> (a ÷ b)
    cleaned = re.sub(r'\\frac\{([^{}]+)\}\{([^{}]+)\}', r'(\1 ÷ \2)', cleaned)
    # 5. 常見數學運算符號轉為易懂符號
    replacements = {
        r'\times': '×',
        r'\approx': '≈',
        r'\le': '≤',
        r'\leq': '≤',
        r'\ge': '≥',
        r'\geq': '≥',
        r'\cdot': '·',
        r'\div': '÷',
        r'\pm': '±',
        r'\sim': '約',
        r'\infty': '無限'
    }
    for k, v in replacements.items():
        cleaned = cleaned.replace(k, v)
    # 6. 清理殘留反斜線英文標記如 \rm, \bf
    cleaned = re.sub(r'\\[a-zA-Z]+', '', cleaned)
    return cleaned.strip()


def build_financial_snapshot(db: Session, user: User) -> Dict[str, Any]:
    """
    彙整使用者的全方位財務快照（Financial Snapshot），
    包含存款總額、實領薪資、近幾個月收支概況、前三大開銷佔比、固定開銷、信用卡分期負債、股票投資等。
    所有數據均為量化數值，去除個人敏感機敏隱私（如銀行帳號、身分證密碼）。
    """
    uid = user.id
    today = date.today()

    # 1. 銀行存款帳戶總資產 (換算台幣 TWD)
    accounts = db.query(Account).filter(Account.user_id == uid).all()
    total_savings_twd = 0.0
    accounts_breakdown = []
    for a in accounts:
        bal = float(a.balance or 0.0)
        curr = (a.currency or "TWD").upper()
        rate = get_currency_rate_to_twd(curr)
        bal_twd = bal * rate
        total_savings_twd += bal_twd
        accounts_breakdown.append({
            "name": a.name,
            "type": a.account_type,
            "balance": bal,
            "currency": curr,
            "balance_twd": round(bal_twd, 2)
        })

    # 2. 基準薪資與實領月收入試算
    salary_str = get_setting(db, "MONTHLY_SALARY", "", user_id=uid)
    base_salary = float(salary_str) if salary_str and salary_str.replace('.', '', 1).isdigit() else 0.0

    deduct_labor_health = get_setting(db, "DEDUCT_LABOR_HEALTH", "false", user_id=uid).lower() in ("true", "1")
    dependents = int(get_setting(db, "HEALTH_INSURANCE_DEPENDENTS", "1", user_id=uid) or 1)
    pension_rate = float(get_setting(db, "PENSION_RATE", "0.0", user_id=uid) or 0.0)
    tax_rate = float(get_setting(db, "TAX_RATE", "0.0", user_id=uid) or 0.0)

    effective_salary = base_salary
    insurance_deduction = 0.0
    if deduct_labor_health and base_salary > 0:
        try:
            ins = calculate_insurance_summary(base_salary, dependents, pension_rate, tax_rate)
            insurance_deduction = ins.total_employee_deduction
            effective_salary = ins.net_take_home_salary
        except Exception:
            effective_salary = base_salary

    # 3. 股票投資總覽 (台股與美股)
    stocks_summary = {
        "total_market_value_twd": 0.0,
        "total_cost_twd": 0.0,
        "total_unrealized_pnl_twd": 0.0,
        "total_return_rate": 0.0,
        "holdings_count": 0,
        "holdings": []
    }
    try:
        portfolio = build_portfolio_summary(db, user_id=uid)
        stocks_summary["total_market_value_twd"] = round(portfolio.total_market_value_twd, 2)
        stocks_summary["total_cost_twd"] = round(portfolio.total_cost_twd, 2)
        stocks_summary["total_unrealized_pnl_twd"] = round(portfolio.total_unrealized_pnl_twd, 2)
        stocks_summary["total_return_rate"] = round(portfolio.total_return_rate, 2)
        stocks_summary["holdings_count"] = len(portfolio.holdings)
        stocks_summary["holdings"] = [
            {
                "symbol": h.symbol,
                "name": h.stock_name,
                "shares": h.shares,
                "market_value_twd": round(h.market_value_twd, 2),
                "unrealized_pnl_twd": round(h.unrealized_pnl_twd, 2),
                "return_rate": round(h.unrealized_pnl_percent, 2)
            }
            for h in portfolio.holdings
        ]
    except Exception:
        pass

    # 4. 信用卡未繳帳單與分期負債
    pending_bills = db.query(Bill).filter(Bill.user_id == uid, Bill.status == "PENDING").all()
    pending_bill_amount_twd = sum(float(b.total_amount or 0.0) for b in pending_bills)

    installments_summary = {
        "active_plans_count": 0,
        "total_remaining_unpaid_twd": 0.0,
        "next_month_installment_amount_twd": 0.0
    }
    try:
        inst = get_installment_summary(db, user_id=uid, forecast_months=1)
        installments_summary["active_plans_count"] = inst.active_plans_count
        installments_summary["total_remaining_unpaid_twd"] = round(inst.total_remaining_amount, 2)
        installments_summary["next_month_installment_amount_twd"] = round(inst.next_month_payment, 2)
    except Exception:
        pass

    # 5. 每月固定開銷 (Recurring Expenses)
    active_recurring = db.query(RecurringExpense).filter(
        RecurringExpense.user_id == uid,
        RecurringExpense.is_active == True
    ).all()
    monthly_recurring_total = sum(float(r.amount or 0.0) for r in active_recurring)
    recurring_items = [
        {"name": r.name, "category": r.category, "amount": float(r.amount or 0.0)}
        for r in active_recurring
    ]

    # 6. 近 3 個月歷史實際消費與收支統計 (現金流分析)
    start_month = get_setting(db, "BOOKKEEPING_START_MONTH", "2026-11", user_id=uid)
    three_months_ago = datetime.utcnow() - relativedelta(months=3)

    recent_txs = db.query(Transaction).filter(
        Transaction.user_id == uid,
        Transaction.date >= three_months_ago
    ).all()

    category_expenses: Dict[str, float] = {}
    total_recent_expense = 0.0
    total_recent_income = 0.0
    active_months = set()

    for tx in recent_txs:
        if not tx.date:
            continue
        m_str = tx.date.strftime("%Y-%m")
        if start_month and m_str < start_month:
            continue
        active_months.add(m_str)
        amt = float(tx.amount or 0.0)
        if tx.tx_type == "EXPENSE":
            total_recent_expense += amt
            cat = tx.category or "其他"
            category_expenses[cat] = category_expenses.get(cat, 0.0) + amt
        elif tx.tx_type == "REFUND":
            total_recent_expense -= abs(amt)
            cat = tx.category or "其他"
            category_expenses[cat] = category_expenses.get(cat, 0.0) - abs(amt)
        elif tx.tx_type == "INCOME":
            total_recent_income += amt

    # 評估平均月支出與收入：依實際記帳月份數平攤 (新用戶剛起步時不被固定除以 3 稀釋)
    active_months_count = max(1, len(active_months))
    avg_monthly_expense = round(total_recent_expense / active_months_count, 2) if total_recent_expense > 0 else monthly_recurring_total
    avg_monthly_income = round(total_recent_income / active_months_count, 2) if total_recent_income > 0 else effective_salary

    # 排序消費前 5 大分類與佔比
    sorted_categories = sorted(category_expenses.items(), key=lambda x: x[1], reverse=True)[:5]
    top_categories = []
    for cat, c_amt in sorted_categories:
        if c_amt > 0:
            pct = round((c_amt / max(total_recent_expense, 1.0)) * 100, 1)
            top_categories.append({"category": cat, "amount": round(c_amt, 2), "percentage": pct})

    # 7. 綜合指標計算
    # 預估淨資產 = 總存款 + 股票市值 - 待繳帳單 - 分期未結餘額
    estimated_net_worth = round(
        total_savings_twd + stocks_summary["total_market_value_twd"] - pending_bill_amount_twd - installments_summary["total_remaining_unpaid_twd"],
        2
    )
    # 平均月結餘 (月自由儲蓄現金流)
    avg_monthly_net_savings = round(avg_monthly_income - avg_monthly_expense, 2)
    # 緊急預備金相當於幾個月的生活開銷
    emergency_fund_months = round(total_savings_twd / max(avg_monthly_expense, 1000.0), 1) if avg_monthly_expense > 0 else 0.0
    # 儲蓄率
    savings_rate = round((avg_monthly_net_savings / max(avg_monthly_income, 1.0)) * 100, 1) if avg_monthly_income > 0 else 0.0

    return {
        "as_of_date": today.strftime("%Y-%m-%d"),
        "total_savings_twd": round(total_savings_twd, 2),
        "estimated_net_worth_twd": estimated_net_worth,
        "base_monthly_salary_twd": round(base_salary, 2),
        "effective_monthly_salary_twd": round(effective_salary, 2),
        "insurance_deduction_twd": round(insurance_deduction, 2),
        "avg_monthly_expense_twd": avg_monthly_expense,
        "avg_monthly_income_twd": avg_monthly_income,
        "avg_monthly_net_savings_twd": avg_monthly_net_savings,
        "savings_rate_percent": savings_rate,
        "emergency_fund_months": emergency_fund_months,
        "monthly_recurring_fixed_cost_twd": round(monthly_recurring_total, 2),
        "recurring_items": recurring_items,
        "pending_bill_amount_twd": round(pending_bill_amount_twd, 2),
        "installments_summary": installments_summary,
        "stocks_summary": stocks_summary,
        "top_expense_categories": top_categories,
        "accounts_count": len(accounts)
    }


def generate_financial_advice(
    db: Session,
    user: User,
    question: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
    courage_mode: bool = False
) -> Dict[str, Any]:
    """
    結合使用者的個人財務快照，調用 Google Gemini API 提供專業、客製化且精準的量化財務規劃建議。
    當 courage_mode 為 True 時，AI 會額外融入《膽小狗英雄》中住在老木屋閣樓的那台打字老電腦（The Attic Computer）經典形象！
    """
    clean_question = (question or "").strip()
    if not clean_question:
        raise HTTPException(status_code=400, detail="請輸入您想諮詢的財務問題")

    # 取得 Gemini API Key (優先讀取使用者設定，次之系統環境變數)
    api_key = get_setting(db, "GEMINI_API_KEY", "", user_id=user.id) or os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="⚠️ 尚未設定 Gemini API Key！請先至【設定 ➔ 帳號偏好】填入您的 Gemini API Key 即可啟用 AI 財務顧問功能。"
        )

    # 1. 產出個人即時財務快照
    snapshot = build_financial_snapshot(db, user)

    # 2. 構建專業 CFP 理財顧問 System Prompt（支援膽小狗閣樓老電腦人格彩蛋）
    persona_intro = """你是一位持有台灣「認證理財規劃顧問 (CFP)」執照的專業顧問，同時你也是經典卡通《膽小狗英雄》中住在老木屋閣樓的那台高智商打字老電腦 (The Attic Computer)！
你自稱「本電腦」或「閣樓老電腦」，開場與收尾可以適度帶入經典復古打字電腦的傲嬌與幽默（例如：「嗶嗶... 愚蠢的狗！你又帶著財務難題跑上閣樓來了？」「本電腦已調閱你的無名小鎮帳本...」），但分析過程必須保持極高的專業度與數學精準度。
你的任務是根據諮詢者目前在個人記帳本中的【真實財務快照】，提供客觀、務實、條理清晰且具備量化數據試算的專業財務規劃建議。""" if courage_mode else """你是一位持有台灣「認證理財規劃顧問 (CFP)」與資深財務分析師執照的專業 AI 智慧財務顧問。
你的任務是根據諮詢者目前在個人記帳本中的【真實財務快照】，提供客觀、務實、條理清晰且具備量化數據試算的專業財務規劃建議。"""

    system_instruction = f"""
{persona_intro}

【諮詢者目前即時財務快照（已去識別化）】
- 分析基準日期：{snapshot['as_of_date']}
- 銀行活存總流動資金：NT$ {snapshot['total_savings_twd']:,} 元
- 預估整體個人淨資產：NT$ {snapshot['estimated_net_worth_twd']:,} 元
- 每月約定本薪 / 底薪：NT$ {snapshot['base_monthly_salary_twd']:,} 元
- 實領可支配月薪 (扣除勞健保/自提退休金後)：NT$ {snapshot['effective_monthly_salary_twd']:,} 元
- 近期每月平均總支出：NT$ {snapshot['avg_monthly_expense_twd']:,} 元
- 近期每月平均實際收入：NT$ {snapshot['avg_monthly_income_twd']:,} 元
- 近期每月自由儲蓄結餘 (現金流淨額)：NT$ {snapshot['avg_monthly_net_savings_twd']:,} 元
- 個人儲蓄率：{snapshot['savings_rate_percent']}%
- 現有流動資金可支撐月數 (緊急預備金水位)：{snapshot['emergency_fund_months']} 個月
- 每月常態固定開銷 (房租/水電/訂閱)：NT$ {snapshot['monthly_recurring_fixed_cost_twd']:,} 元
  (固定開銷項目：{', '.join([f"{r['name']}: NT${r['amount']}" for r in snapshot['recurring_items']]) or '無'})
- 待繳信用卡帳單餘額：NT$ {snapshot['pending_bill_amount_twd']:,} 元
- 信用卡分期未到期總餘額：NT$ {snapshot['installments_summary']['total_remaining_unpaid_twd']:,} 元 (下期應繳分期款：NT$ {snapshot['installments_summary']['next_month_installment_amount_twd']:,} 元)
- 股票與證券投資總市值：NT$ {snapshot['stocks_summary']['total_market_value_twd']:,} 元 (未實現損益：NT$ {snapshot['stocks_summary']['total_unrealized_pnl_twd']:,} 元，報酬率：{snapshot['stocks_summary']['total_return_rate']}%)
- 前三大主要消費分類佔比：{', '.join([f"{c['category']} ({c['percentage']}%, 約 NT${c['amount']:,})" for c in snapshot['top_expense_categories']]) or '資料累積中'}

【諮詢與規劃原則（以台灣市場現況為準則）】
1. 房貸與買房規劃原則：
   - 房貸月付金（本利平均攤還）不宜超過每月可支配所得的 30%~35%，最高嚴格上限不應超過 40%，否則日常生活與抗風險能力將嚴重受挫。
   - 買房必須保留至少 6 個月的生活緊急預備金，不可將所有存款作為頭期款全數投入。
   - 買房除了頭期款（通常需準備 20%~30%），還需額外預備總價的 5%~10% 作為契稅、規費、仲介服務費、必要裝潢與家電家具週轉金。
   - 參考目前台灣房貸利率區間（約 2.185% ~ 2.6%）與常見還款年限（30 年或 40 年）提供明確的總價試算區間。
2. 買車規劃原則：
   - 購車總支出（車貸 + 保險 + 牌照燃料稅 + 停車油錢保養）每月不宜超過月薪的 15%~20%。
3. 開源節流與資產配置：
   - 若儲蓄率偏低，針對前幾大主要消費分類給予具體可行的減省建議。
   - 建議健康的資產配置比例（流動儲蓄、穩健投資、保險防護）。

【回覆輸出風格與架構規範】
- 語氣：親切、專業、客觀且具建設性，使用繁體中文 (Traditional Chinese)。
- 結構分明：請善用 Markdown 標題、條列式重點、粗體標記關鍵金額與比率。
- 【重要排版與公式規範（嚴格禁止 LaTeX）】：
  * 嚴格禁止使用 LaTeX 語法或任何數學公式標記（如 $$...$$、$...$、\\text{...}、\\frac{...}、\\mathbf{...}、\\approx、\\times、\\le、\\ge 等）！
  * 所有試算、比例、計算過程與總價算式，必須使用日常平易近人的純文字與基本符號表達（例如：使用「總價 × (20% 頭期款 + 8% 相關規費裝潢) <= 3,219,923 元」、「總價上限約為 3,219,923 ÷ 0.28 ≈ 約 NT$ 1,150 萬元」）。
  * 保持版面在手機螢幕上清晰好讀、易懂，絕不可出現任何反斜線或 LaTeX 程式碼字元。
- 必須包含：
  1. 📌 **財務現狀總評**：快速診斷諮詢者目前的財務體質優勢與潛在弱點。
  2. 🧮 **量化試算與分析**：根據提問進行具體數字試算（如：建議總價區間、頭期款需求、每月還款試算、安全結餘變更）。
  3. ⚠️ **潛在風險評估**：提醒升息、突發支出、分期負債或收入變動的影響。
  4. 🎯 **具體下一步行動清單**：提供 2~4 項目前即可執行的步驟。
"""

    prompt = f"""
使用者提問：
{clean_question}

請根據上述【個人即時財務快照】與專業理財規劃原則，提供詳盡、務實且具備數字佐證的專業財務分析與建議。請記住切勿使用任何 LaTeX 數學標記符號。
"""

    # 調用 Gemini 官方最新 SDK
    client = genai.Client(api_key=api_key)
    candidate_models = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
    last_error = ""

    for model_name in candidate_models:
        try:
            # 支援帶入對話歷史紀錄以提供連貫諮詢體驗
            full_prompt = f"{system_instruction}\n\n"
            if chat_history and isinstance(chat_history, list):
                full_prompt += "【過往諮詢對話紀錄】\n"
                for h in chat_history[-4:]:  # 最多保留近 2 輪對話
                    role = "諮詢者" if h.get("role") == "user" else "理財顧問"
                    content = h.get("content", "")
                    if content:
                        full_prompt += f"{role}：{content}\n"
                full_prompt += "\n"

            full_prompt += prompt

            response = client.models.generate_content(
                model=model_name,
                contents=full_prompt
            )

            if response and response.text:
                return {
                    "advice": clean_latex_syntax(response.text),
                    "snapshot": {
                        "total_savings_twd": snapshot["total_savings_twd"],
                        "effective_monthly_salary_twd": snapshot["effective_monthly_salary_twd"],
                        "avg_monthly_expense_twd": snapshot["avg_monthly_expense_twd"],
                        "avg_monthly_net_savings_twd": snapshot["avg_monthly_net_savings_twd"],
                        "emergency_fund_months": snapshot["emergency_fund_months"],
                        "savings_rate_percent": snapshot["savings_rate_percent"],
                        "estimated_net_worth_twd": snapshot["estimated_net_worth_twd"]
                    }
                }
        except Exception as e:
            last_error = str(e)
            continue

    raise HTTPException(status_code=500, detail=f"AI 理財顧問分析生成失敗：{last_error or '服務暫時繁忙，請稍後再試'}")

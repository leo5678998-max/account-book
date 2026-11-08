from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import User
from ..services.auth_service import get_current_user
from ..services.ai_advisor_service import build_financial_snapshot, generate_financial_advice

router = APIRouter(prefix="/api/ai/advisor", tags=["AI Advisor"])


class AdvisorQuestionRequest(BaseModel):
    question: str
    history: Optional[List[Dict[str, str]]] = None


class AdvisorAdviceResponse(BaseModel):
    advice: str
    snapshot: Dict[str, Any]


@router.get("/snapshot")
def get_user_financial_snapshot(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    取得當前使用者的個人財務快照分析指標（包含總存款、實領收入、近期月平均支出、淨資產等）
    """
    return build_financial_snapshot(db, current_user)


@router.post("/ask", response_model=AdvisorAdviceResponse)
def ask_financial_advisor(
    req: AdvisorQuestionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    向 AI 智慧理財顧問諮詢問題（如：買房建議、購車預算、收支最佳化），
    系統將自動結合使用者的真實財務快照進行專業量化分析與建議。
    """
    result = generate_financial_advice(
        db=db,
        user=current_user,
        question=req.question,
        chat_history=req.history
    )
    return AdvisorAdviceResponse(
        advice=result["advice"],
        snapshot=result["snapshot"]
    )

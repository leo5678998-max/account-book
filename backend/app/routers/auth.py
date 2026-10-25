from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import User, Account
from ..schemas import (
    UserRegister,
    UserLogin,
    UserProfileUpdate,
    UserResponse,
    TokenResponse
)
from ..services.auth_service import (
    hash_password,
    verify_password,
    create_access_token,
    get_current_user
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse)
def register_user(req: UserRegister, db: Session = Depends(get_db)):
    """註冊新使用者帳號，並初始化獨立的帳本環境"""
    username = (req.username or "").strip()
    password = req.password or ""

    if len(username) < 2 or len(username) > 40:
        raise HTTPException(status_code=400, detail="帳號長度須介於 2 至 40 個字元之間")
    if len(password) < 4:
        raise HTTPException(status_code=400, detail="密碼長度至少須為 4 個字元")

    existing = db.query(User).filter(User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="此帳號名稱已被註冊，請換一個帳號")

    display_name = (req.display_name or "").strip() or username
    new_user = User(
        username=username,
        password_hash=hash_password(password),
        display_name=display_name
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # 為新註冊的使用者自動建立一個預設活存帳戶，方便立即開始記帳
    default_acc = Account(
        user_id=new_user.id,
        name="台幣活存 (預設)",
        account_type="SAVINGS",
        balance=0.0,
        currency="TWD",
        is_dbs_default_debit=True
    )
    db.add(default_acc)
    db.commit()

    token = create_access_token(db, new_user.id, new_user.username)
    return TokenResponse(
        access_token=token,
        user=UserResponse.from_orm(new_user)
    )


@router.post("/login", response_model=TokenResponse)
def login_user(req: UserLogin, db: Session = Depends(get_db)):
    """使用者帳號密碼登入"""
    username = (req.username or "").strip()
    password = req.password or ""

    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="帳號或密碼錯誤")

    token = create_access_token(db, user.id, user.username)
    return TokenResponse(
        access_token=token,
        user=UserResponse.from_orm(user)
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """取得目前登入的使用者資訊"""
    return current_user


@router.put("/profile", response_model=UserResponse)
def update_profile(
    req: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新顯示名稱或修改登入密碼"""
    if req.display_name is not None and req.display_name.strip():
        current_user.display_name = req.display_name.strip()

    if req.new_password:
        if len(req.new_password) < 4:
            raise HTTPException(status_code=400, detail="新密碼長度至少須為 4 個字元")
        if req.current_password and not verify_password(req.current_password, current_user.password_hash):
            raise HTTPException(status_code=400, detail="目前密碼輸入不正確")
        current_user.password_hash = hash_password(req.new_password)

    db.commit()
    db.refresh(current_user)
    return current_user


from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.auth import LoginRequest, RegisterRequest, LoginResponse, UserResponse
from app.services.auth_service import auth_service
from app.security import get_current_user
from app.models.user import User

router = APIRouter()


@router.post("/register", response_model=LoginResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    try:
        result = auth_service.register(
            db=db,
            username=req.username,
            password=req.password,
            name=req.name,
            role=req.role,
            grade=req.grade,
            major=req.major,
        )
        token = auth_service.login(db, req.username, req.password)
        return token
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/login", response_model=LoginResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    try:
        return auth_service.login(db, req.username, req.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/me", response_model=UserResponse)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return auth_service.get_me(db, current_user)

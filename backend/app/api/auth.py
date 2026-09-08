"""Authentication endpoints (Phase 8: auth foundation).

`POST /auth/register`, `POST /auth/login` only — no route protection is
introduced here; existing endpoints are untouched.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserOut
from app.services import auth as svc

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(req: RegisterRequest, db: Session = Depends(get_db)) -> UserOut:
    try:
        user = svc.register_user(db, req.email, req.password)
    except svc.EmailAlreadyRegistered as exc:
        raise HTTPException(
            status_code=409, detail="An account with this email already exists"
        ) from exc
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    try:
        user = svc.authenticate_user(db, req.email, req.password)
    except svc.InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        ) from exc
    return TokenResponse(access_token=svc.create_access_token(user.id))

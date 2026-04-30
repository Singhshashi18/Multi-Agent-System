from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.models.database import get_db
from app.models.schemas import AuthResponse, LoginRequest, SignupRequest
from app.models.user import User

router = APIRouter(tags=["auth"])
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def create_access_token(subject: str) -> str:
    expire_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": subject, "exp": expire_at}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


@router.post("/auth/signup", response_model=AuthResponse)
async def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> AuthResponse:
    existing = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")

    new_user = User(
        full_name=payload.full_name.strip(),
        email=payload.email.lower().strip(),
        password_hash=pwd_context.hash(payload.password),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    token = create_access_token(str(new_user.id))
    return AuthResponse(
        access_token=token,
        user={"id": str(new_user.id), "full_name": new_user.full_name, "email": new_user.email},
    )


@router.post("/auth/login", response_model=AuthResponse)
async def login(payload: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if not user or not pwd_context.verify(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = create_access_token(str(user.id))
    return AuthResponse(
        access_token=token,
        user={"id": str(user.id), "full_name": user.full_name, "email": user.email},
    )

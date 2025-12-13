# backend/app/core/auth.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel
import bcrypt

from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User as UserModel

router = APIRouter()

# This must match your login route path below
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# ----------------- Response models -----------------
class User(BaseModel):
    id: int
    username: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ----------------- Helpers -----------------
def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def get_user_by_username(db: Session, username: str) -> UserModel | None:
    return db.query(UserModel).filter(UserModel.username == username).first()


# ----------------- Routes -----------------
@router.post("/auth/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = get_user_by_username(db, form_data.username)

    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    # simple dev token for now
    return {"access_token": f"dev-{user.username}", "token_type": "bearer"}


def _username_from_token(token: str) -> str:
    # accept either "dev-ethan" or just "ethan"
    if token.startswith("dev-"):
        return token[4:]
    return token


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> UserModel:
    username = _username_from_token(token)
    user = get_user_by_username(db, username)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


@router.get("/auth/me", response_model=User)
def read_me(current_user: UserModel = Depends(get_current_user)):
    return {"id": int(current_user.id), "username": current_user.username}
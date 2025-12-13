# backend/app/routers/collections.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..core.auth import User, get_current_user
from ..db import get_db
from ..models import Collection as CollectionModel, Set as SetModel, User as UserModel

router = APIRouter()


def _resolve_set_num(db: Session, set_num_or_plain: str) -> str:
    """
    Accepts '10305' or '10305-1' and returns canonical set_num in DB ('10305-1').
    """
    raw = (set_num_or_plain or "").strip()
    if not raw:
        raise HTTPException(status_code=404, detail="Set not found")

    plain = raw.split("-")[0].lower()
    plain_expr = func.split_part(SetModel.set_num, "-", 1)

    canonical = db.execute(
        select(SetModel.set_num)
        .where(
            or_(
                func.lower(SetModel.set_num) == raw.lower(),
                func.lower(plain_expr) == plain,
            )
        )
        .limit(1)
    ).scalar_one_or_none()

    if not canonical:
        raise HTTPException(status_code=404, detail="Set not found")

    return canonical


def _row_to_item(c: CollectionModel, username: Optional[str] = None) -> Dict[str, Any]:
    # Keep this shape close to what your frontend expects today
    return {
        "username": username,  # optional
        "set_num": c.set_num,
        "type": c.type,
        "created_at": c.created_at,
    }


@router.post("/owned", status_code=status.HTTP_201_CREATED)
def add_owned(
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    POST /collections/owned
    Body: { "set_num": "10305-1" } (or "10305")
    """
    set_num = payload.get("set_num")
    canonical = _resolve_set_num(db, set_num)

    # If it exists already, treat as conflict
    existing = db.execute(
        select(CollectionModel).where(
            CollectionModel.user_id == current_user.id,
            CollectionModel.set_num == canonical,
            CollectionModel.type == "owned",
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Already in owned")

    # Optional: if it was in wishlist, remove that row
    wish = db.execute(
        select(CollectionModel).where(
            CollectionModel.user_id == current_user.id,
            CollectionModel.set_num == canonical,
            CollectionModel.type == "wishlist",
        )
    ).scalar_one_or_none()
    if wish:
        db.delete(wish)

    row = CollectionModel(user_id=current_user.id, set_num=canonical, type="owned")
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_to_item(row, current_user.username)


@router.post("/wishlist", status_code=status.HTTP_201_CREATED)
def add_wishlist(
    payload: Dict[str, Any],
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    POST /collections/wishlist
    Body: { "set_num": "10305-1" } (or "10305")
    """
    set_num = payload.get("set_num")
    canonical = _resolve_set_num(db, set_num)

    existing = db.execute(
        select(CollectionModel).where(
            CollectionModel.user_id == current_user.id,
            CollectionModel.set_num == canonical,
            CollectionModel.type == "wishlist",
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=400, detail="Already in wishlist")

    row = CollectionModel(user_id=current_user.id, set_num=canonical, type="wishlist")
    db.add(row)
    db.commit()
    db.refresh(row)
    return _row_to_item(row, current_user.username)


@router.delete("/owned/{set_num}", status_code=status.HTTP_204_NO_CONTENT)
def remove_owned(
    set_num: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    canonical = _resolve_set_num(db, set_num)

    existing = db.execute(
        select(CollectionModel).where(
            CollectionModel.user_id == current_user.id,
            CollectionModel.set_num == canonical,
            CollectionModel.type == "owned",
        )
    ).scalar_one_or_none()

    if not existing:
        raise HTTPException(status_code=404, detail="Not in owned")

    db.delete(existing)
    db.commit()
    return None


@router.delete("/wishlist/{set_num}", status_code=status.HTTP_204_NO_CONTENT)
def remove_wishlist(
    set_num: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    canonical = _resolve_set_num(db, set_num)

    existing = db.execute(
        select(CollectionModel).where(
            CollectionModel.user_id == current_user.id,
            CollectionModel.set_num == canonical,
            CollectionModel.type == "wishlist",
        )
    ).scalar_one_or_none()

    if not existing:
        raise HTTPException(status_code=404, detail="Not in wishlist")

    db.delete(existing)
    db.commit()
    return None


@router.get("/me/owned")
def list_my_owned(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(CollectionModel)
        .where(CollectionModel.user_id == current_user.id, CollectionModel.type == "owned")
        .order_by(CollectionModel.created_at.desc())
    ).scalars().all()
    return [_row_to_item(r, current_user.username) for r in rows]


@router.get("/me/wishlist")
def list_my_wishlist(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = db.execute(
        select(CollectionModel)
        .where(CollectionModel.user_id == current_user.id, CollectionModel.type == "wishlist")
        .order_by(CollectionModel.created_at.desc())
    ).scalars().all()
    return [_row_to_item(r, current_user.username) for r in rows]


@router.get("/users/{username}/owned")
def list_owned_by_user(
    username: str,
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=500),
):
    user = db.execute(
        select(UserModel).where(func.lower(UserModel.username) == username.lower()).limit(1)
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rows = db.execute(
        select(CollectionModel)
        .where(CollectionModel.user_id == user.id, CollectionModel.type == "owned")
        .order_by(CollectionModel.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [_row_to_item(r, user.username) for r in rows]


@router.get("/users/{username}/wishlist")
def list_wishlist_by_user(
    username: str,
    db: Session = Depends(get_db),
    limit: int = Query(200, ge=1, le=500),
):
    user = db.execute(
        select(UserModel).where(func.lower(UserModel.username) == username.lower()).limit(1)
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rows = db.execute(
        select(CollectionModel)
        .where(CollectionModel.user_id == user.id, CollectionModel.type == "wishlist")
        .order_by(CollectionModel.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [_row_to_item(r, user.username) for r in rows]
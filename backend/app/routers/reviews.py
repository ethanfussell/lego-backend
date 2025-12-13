# backend/app/routers/reviews.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from ..core.auth import User, get_current_user
from ..db import get_db
from ..models import Review as ReviewModel, Set as SetModel
from ..schemas.review import Review, ReviewCreate

router = APIRouter()


def _resolve_set_num(db: Session, set_num_or_plain: str) -> str:
    """
    Accepts '10305' or '10305-1' and returns the canonical set_num in DB ('10305-1').
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


def _to_api_dict(r: ReviewModel) -> Dict[str, Any]:
    username = getattr(getattr(r, "user", None), "username", None)

    return {
        "id": int(r.id),
        "set_num": r.set_num,
        "user": username or "unknown",
        "rating": float(r.rating) if r.rating is not None else None,
        "text": r.text,
        "created_at": r.created_at,
        "likes_count": 0,
        "liked_by": [],
    }


@router.get("/{set_num}/reviews", response_model=List[Review])
def list_reviews_for_set(
    set_num: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """
    GET /sets/{set_num}/reviews?limit=50
    Returns newest-first reviews for the set.
    """
    canonical = _resolve_set_num(db, set_num)

    rows = (
        db.execute(
            select(ReviewModel)
            .options(joinedload(ReviewModel.user))
            .where(ReviewModel.set_num == canonical)
            .order_by(ReviewModel.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    return [_to_api_dict(r) for r in rows]


@router.get("/{set_num}/reviews/me", response_model=Optional[Review])
def get_my_review_for_set(
    set_num: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Optional[Dict[str, Any]]:
    """
    GET /sets/{set_num}/reviews/me
    Returns the current user's review for this set, or null if none exists.
    """
    canonical = _resolve_set_num(db, set_num)

    row = (
        db.execute(
            select(ReviewModel)
            .options(joinedload(ReviewModel.user))
            .where(
                ReviewModel.user_id == current_user.id,
                ReviewModel.set_num == canonical,
            )
            .limit(1)
        )
        .scalar_one_or_none()
    )

    if not row:
        return None

    return _to_api_dict(row)


@router.post("/{set_num}/reviews", response_model=Review)
def create_or_update_review(
    set_num: str,
    payload: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    POST /sets/{set_num}/reviews

    Upsert:
    - if review exists for (user_id, set_num) -> update rating/text
    - else create a new review row
    """
    canonical = _resolve_set_num(db, set_num)

    existing = (
        db.execute(
            select(ReviewModel)
            .options(joinedload(ReviewModel.user))
            .where(
                ReviewModel.user_id == current_user.id,
                ReviewModel.set_num == canonical,
            )
            .limit(1)
        )
        .scalar_one_or_none()
    )

    if existing:
        if payload.rating is not None:
            existing.rating = payload.rating
        if payload.text is not None:
            existing.text = payload.text

        db.add(existing)
        db.commit()
        db.refresh(existing)
        return _to_api_dict(existing)

    new_row = ReviewModel(
        user_id=current_user.id,
        set_num=canonical,
        rating=payload.rating,
        text=payload.text,
    )
    db.add(new_row)
    db.commit()
    db.refresh(new_row)

    # ensure user is present for response dict
    new_row = (
        db.execute(
            select(ReviewModel)
            .options(joinedload(ReviewModel.user))
            .where(ReviewModel.id == new_row.id)
            .limit(1)
        )
        .scalar_one()
    )

    return _to_api_dict(new_row)


@router.delete("/{set_num}/reviews/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_review(
    set_num: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """
    DELETE /sets/{set_num}/reviews/me
    Deletes ONLY the current user's review for that set.
    """
    canonical = _resolve_set_num(db, set_num)

    existing = db.execute(
        select(ReviewModel).where(
            ReviewModel.user_id == current_user.id,
            ReviewModel.set_num == canonical,
        )
    ).scalar_one_or_none()

    if not existing:
        raise HTTPException(status_code=404, detail="Review not found")

    db.delete(existing)
    db.commit()
    return None
# backend/app/routers/feed.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, desc
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Set as SetModel, Review as ReviewModel

router = APIRouter()


def _model_to_dict(obj: Any) -> Dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}  # type: ignore


@router.get("/trending")
def trending(
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(20, ge=1, le=100),
):
    """
    Trending sets based on ratings in the last N days.
    Returns the SAME shape as /sets list/detail (includes average_rating + rating_count + rating_avg).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    rating_sq = (
        select(
            ReviewModel.set_num.label("set_num"),
            func.avg(ReviewModel.rating).label("avg_rating"),
            func.count(ReviewModel.rating).label("rating_count"),
        )
        .where(
            ReviewModel.rating.isnot(None),
            ReviewModel.created_at >= cutoff,
        )
        .group_by(ReviewModel.set_num)
        .subquery()
    )

    stmt = (
        select(
            SetModel,
            func.coalesce(rating_sq.c.avg_rating, 0.0).label("avg_rating"),
            func.coalesce(rating_sq.c.rating_count, 0).label("rating_count"),
        )
        .join(rating_sq, rating_sq.c.set_num == SetModel.set_num)  # only sets with ratings in window
        .order_by(
            desc(func.coalesce(rating_sq.c.rating_count, 0)),
            desc(func.coalesce(rating_sq.c.avg_rating, 0.0)),
        )
        .limit(limit)
    )

    rows = db.execute(stmt).all()

    out: List[Dict[str, Any]] = []
    for set_obj, avg_rating, rating_count in rows:
        d = _model_to_dict(set_obj)
        d["average_rating"] = float(avg_rating or 0.0)
        d["rating_count"] = int(rating_count or 0)
        d["rating_avg"] = d["average_rating"]  # alias for older frontend code
        out.append(d)

    return out
# backend/app/routers/sets.py
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import case, desc, asc, func, or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Set, Review  # matches your models.py

from ..data.offers import get_offers_for_set
from ..schemas.pricing import StoreOffer

router = APIRouter()


def _model_to_dict(obj: Any) -> Dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}  # type: ignore


def _plain_expr():
    # Postgres: split_part('10305-1','-',1) -> '10305'
    return func.split_part(Set.set_num, "-", 1)


def _fuzzy_score(row: Dict[str, Any], q: str) -> float:
    q = (q or "").strip().lower()
    if not q:
        return 0.0

    candidates = [
        (row.get("name") or "").lower(),
        (row.get("theme") or "").lower(),
        (row.get("set_num") or "").lower(),
    ]
    best = 0.0
    for t in candidates:
        if not t:
            continue
        best = max(best, SequenceMatcher(None, q, t).ratio())
    return best


def _relevance_case(q_clean: str):
    q_like = f"%{q_clean}%"
    q_prefix = f"{q_clean}%"

    return (
        case((func.lower(_plain_expr()) == q_clean, 100), else_=0)
        + case((func.lower(Set.set_num) == q_clean, 90), else_=0)
        + case((func.lower(Set.name).like(q_prefix), 60), else_=0)
        + case((func.lower(Set.name).like(q_like), 40), else_=0)
        + case((func.lower(Set.theme).like(q_like), 20), else_=0)
    )


@router.get("")
def list_sets(
    response: Response,
    db: Session = Depends(get_db),
    q: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    sort: str = Query("relevance", description="relevance | name | year | pieces | rating"),
    order: Optional[str] = Query(None, description="asc | desc"),
):
    allowed_sorts = {"relevance", "name", "year", "pieces", "rating"}
    if sort not in allowed_sorts:
        raise HTTPException(status_code=400, detail=f"Invalid sort '{sort}'")

    q_clean = (q or "").strip().lower()
    if order is None:
        order = "desc" if sort in {"relevance", "rating"} else "asc"
    order = order.lower()
    reverse = order == "desc"

    rating_sq = (
        select(
            Review.set_num.label("set_num"),
            func.avg(Review.rating).label("avg_rating"),
            func.count(Review.rating).label("rating_count"),
        )
        .where(Review.rating.isnot(None))
        .group_by(Review.set_num)
        .subquery()
    )

    stmt = (
        select(
            Set,
            func.coalesce(rating_sq.c.avg_rating, 0.0).label("avg_rating"),
            func.coalesce(rating_sq.c.rating_count, 0).label("rating_count"),
        )
        .outerjoin(rating_sq, rating_sq.c.set_num == Set.set_num)
    )

    if q_clean:
        like = f"%{q_clean}%"
        stmt = stmt.where(
            or_(
                func.lower(Set.name).like(like),
                func.lower(Set.theme).like(like),
                func.lower(Set.set_num).like(like),
                func.lower(_plain_expr()) == q_clean,
            )
        )

    # total count
    count_stmt = select(func.count()).select_from(Set)
    if q_clean:
        like = f"%{q_clean}%"
        count_stmt = count_stmt.where(
            or_(
                func.lower(Set.name).like(like),
                func.lower(Set.theme).like(like),
                func.lower(Set.set_num).like(like),
                func.lower(_plain_expr()) == q_clean,
            )
        )
    total = db.execute(count_stmt).scalar_one()
    response.headers["X-Total-Count"] = str(total)

    # sort
    if sort == "relevance":
        if q_clean:
            score = _relevance_case(q_clean).label("_relevance")
            stmt = stmt.order_by(
                desc(score),
                desc(func.coalesce(rating_sq.c.rating_count, 0)),
                desc(func.coalesce(rating_sq.c.avg_rating, 0.0)),
            )
        else:
            stmt = stmt.order_by(asc(func.lower(Set.name)))
    elif sort == "name":
        stmt = stmt.order_by(desc(func.lower(Set.name)) if reverse else asc(func.lower(Set.name)))
    elif sort == "year":
        stmt = stmt.order_by(desc(Set.year) if reverse else asc(Set.year))
    elif sort == "pieces":
        stmt = stmt.order_by(desc(Set.pieces) if reverse else asc(Set.pieces))
    elif sort == "rating":
        stmt = stmt.order_by(
            desc(func.coalesce(rating_sq.c.avg_rating, 0.0)) if reverse else asc(func.coalesce(rating_sq.c.avg_rating, 0.0)),
            desc(func.coalesce(rating_sq.c.rating_count, 0)) if reverse else asc(func.coalesce(rating_sq.c.rating_count, 0)),
        )

    offset = (page - 1) * limit
    rows = db.execute(stmt.offset(offset).limit(limit)).all()

    out: List[Dict[str, Any]] = []
    for set_obj, avg_rating, rating_count in rows:
        d = _model_to_dict(set_obj)
        d["average_rating"] = float(avg_rating or 0.0)
        d["rating_count"] = int(rating_count or 0)
        d["rating_avg"] = d["average_rating"]  # alias for older frontend code
        out.append(d)

    return out


@router.get("/suggest")
def suggest_sets(
    db: Session = Depends(get_db),
    q: str = Query(..., min_length=1),
    limit: int = Query(6, ge=1, le=20),
):
    q_clean = (q or "").strip().lower()
    like = f"%{q_clean}%"

    # Candidate pool from direct matches (DB cheap)
    candidates = db.execute(
        select(Set).where(
            or_(
                func.lower(Set.name).like(like),
                func.lower(Set.theme).like(like),
                func.lower(Set.set_num).like(like),
                func.lower(_plain_expr()) == q_clean,
            )
        ).limit(300)
    ).scalars().all()

    # Fuzzy rank in Python (small pool)
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for s in candidates:
        d = _model_to_dict(s)

        base = 0.0
        name = (d.get("name") or "").lower()
        theme = (d.get("theme") or "").lower()
        set_num = (d.get("set_num") or "").lower()
        plain = set_num.split("-")[0]

        direct = False
        if plain == q_clean:
            base += 120; direct = True
        if set_num == q_clean:
            base += 110; direct = True
        if name.startswith(q_clean):
            base += 80; direct = True
        if q_clean in name:
            base += 60; direct = True
        if q_clean in theme:
            base += 30; direct = True

        if not direct:
            fz = _fuzzy_score(d, q_clean)
            if fz < 0.5:
                continue
            base += fz * 50.0

        # popularity = review count (capped)
        cnt = db.execute(
            select(func.count(Review.rating)).where(
                Review.set_num == d["set_num"],
                Review.rating.isnot(None),
            )
        ).scalar_one()
        pop = min(int(cnt or 0), 50)

        scored.append((base + pop, d))

    scored.sort(key=lambda t: t[0], reverse=True)
    top = [d for _, d in scored[:limit]]

    # Frontend expects: set_num, name, ip/theme, year
    return [
        {"set_num": d.get("set_num"), "name": d.get("name"), "ip": d.get("theme"), "year": d.get("year")}
        for d in top
    ]


@router.get("/{set_num}")
def get_set(set_num: str, db: Session = Depends(get_db)):
    raw = (set_num or "").strip()
    plain = raw.split("-")[0].lower()

    s = db.execute(
        select(Set).where(
            or_(
                func.lower(Set.set_num) == raw.lower(),
                func.lower(_plain_expr()) == plain,
            )
        ).limit(1)
    ).scalar_one_or_none()

    if not s:
        raise HTTPException(status_code=404, detail="Set not found")

    avg, cnt = db.execute(
        select(
            func.coalesce(func.avg(Review.rating), 0.0),
            func.coalesce(func.count(Review.rating), 0),
        ).where(Review.set_num == s.set_num, Review.rating.isnot(None))
    ).one()

    out = _model_to_dict(s)
    out["average_rating"] = float(avg or 0.0)
    out["rating_count"] = int(cnt or 0)
    out["rating_avg"] = out["average_rating"]
    return out


@router.get("/{set_num}/offers", response_model=List[StoreOffer])
def get_set_offers(set_num: str, db: Session = Depends(get_db)):
    raw = (set_num or "").strip()
    plain = raw.split("-")[0].lower()

    s = db.execute(
        select(Set).where(
            or_(
                func.lower(Set.set_num) == raw.lower(),
                func.lower(_plain_expr()) == plain,
            )
        ).limit(1)
    ).scalar_one_or_none()

    if not s:
        raise HTTPException(status_code=404, detail="Set not found")

    plain_num = (s.set_num or "").split("-")[0]
    return get_offers_for_set(plain_num)

@router.get("/trending")
def trending_sets(
    response: Response,
    db: Session = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(12, ge=1, le=50),
):
    """
    GET /sets/trending?days=30&limit=12

    Trending = most reviews created in the last N days.
    (ties broken by avg rating, then total rating_count)
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    recent_sq = (
        select(
            Review.set_num.label("set_num"),
            func.count(Review.id).label("recent_reviews"),
            func.avg(Review.rating).label("avg_rating"),
            func.count(Review.rating).label("rating_count"),
        )
        .where(Review.created_at >= cutoff)
        .group_by(Review.set_num)
        .subquery()
    )

    stmt = (
        select(
            Set,
            recent_sq.c.recent_reviews,
            func.coalesce(recent_sq.c.avg_rating, 0.0).label("avg_rating"),
            func.coalesce(recent_sq.c.rating_count, 0).label("rating_count"),
        )
        .join(recent_sq, recent_sq.c.set_num == Set.set_num)
        .order_by(
            desc(recent_sq.c.recent_reviews),
            desc(func.coalesce(recent_sq.c.avg_rating, 0.0)),
            desc(func.coalesce(recent_sq.c.rating_count, 0)),
        )
        .limit(limit)
    )

    rows = db.execute(stmt).all()
    response.headers["X-Total-Count"] = str(len(rows))

    out = []
    for set_obj, recent_reviews, avg_rating, rating_count in rows:
        d = _model_to_dict(set_obj)
        d["recent_reviews"] = int(recent_reviews or 0)
        d["average_rating"] = float(avg_rating or 0.0)
        d["rating_count"] = int(rating_count or 0)
        d["rating_avg"] = d["average_rating"]  # keep your frontend alias
        out.append(d)

    return out
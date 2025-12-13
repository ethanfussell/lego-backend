# backend/scripts/seeds_sets_db.py
from __future__ import annotations

from sqlalchemy.dialects.postgresql import insert

from app.db import SessionLocal, engine, Base
from app.models import Set
from app.data.sets import load_cached_sets


def main() -> None:
    # Make sure tables exist
    Base.metadata.create_all(bind=engine)

    sets = load_cached_sets()
    print(f"Loaded {len(sets)} sets from cache.")

    if not sets:
        print("No sets found in cache. Nothing to seed.")
        return

    rows = []
    for s in sets:
        rows.append(
            {
                "set_num": s.get("set_num"),
                "name": s.get("name") or "Unknown",
                "year": s.get("year"),
                "theme": s.get("theme"),
                "pieces": s.get("pieces"),
                "image_url": s.get("image_url"),
            }
        )

    # Upsert / ignore duplicates by set_num
    stmt = insert(Set).values(rows)
    stmt = stmt.on_conflict_do_nothing(index_elements=["set_num"])

    db = SessionLocal()
    try:
        result = db.execute(stmt)
        db.commit()
        # result.rowcount can be None depending on driver, but usually works
        print(f"Inserted ~{result.rowcount} new rows into sets.")
    finally:
        db.close()

    print("Done.")


if __name__ == "__main__":
    main()
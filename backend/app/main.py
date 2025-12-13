from pathlib import Path
from dotenv import load_dotenv

# loads backend/.env no matter where you run uvicorn from
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from .core import auth as auth_router
from .routers import sets as sets_router
from .routers import reviews as reviews_router
from .routers import collections as collections_router
from .routers import lists as lists_router
from .routers import users as users_router
from .routers import feed as feed_router

from .api import themes
from sqlalchemy.orm import Session
from sqlalchemy import text
from .db import get_db

app = FastAPI(title="LEGO API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)

@app.get("/")
def root():
    return {"status": "ok", "message": "LEGO API is running"}

# Auth
app.include_router(auth_router.router)

# Sets search + detail
app.include_router(sets_router.router, prefix="/sets", tags=["sets"])

# Reviews (attached under /sets)
app.include_router(reviews_router.router, prefix="/sets", tags=["reviews"])

# Owned / wishlist collections
app.include_router(
    collections_router.router,
    prefix="/collections",
    tags=["collections"],
)

# Custom lists
app.include_router(lists_router.router, tags=["lists"])

# Users
app.include_router(users_router.router, tags=["users"])

app.include_router(themes.router)

@app.get("/db/ping")
def db_ping(db: Session = Depends(get_db)):
    row = db.execute(
        text("select current_database() as db, current_user as user")
    ).mappings().one()
    return dict(row)

app.include_router(feed_router.router, prefix="/feed", tags=["feed"])
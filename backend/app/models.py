# backend/app/models.py
from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    collections = relationship(
        "Collection",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reviews = relationship(
        "Review",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Set(Base):
    __tablename__ = "sets"

    set_num = Column(String, primary_key=True)
    name = Column(String, nullable=False, index=True)
    year = Column(Integer)
    theme = Column(String, index=True)
    pieces = Column(Integer)
    image_url = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    collections = relationship(
        "Collection",
        back_populates="set",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    reviews = relationship(
        "Review",
        back_populates="set",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Collection(Base):
    __tablename__ = "collections"

    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    set_num = Column(
        String,
        ForeignKey("sets.set_num", ondelete="CASCADE"),
        primary_key=True,
    )
    type = Column(String, primary_key=True)  # 'owned' | 'wishlist'
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("type in ('owned','wishlist')", name="collections_type_check"),
        Index("ix_collections_user_type", "user_id", "type"),
        Index("ix_collections_set_type", "set_num", "type"),
    )

    user = relationship("User", back_populates="collections")
    set = relationship("Set", back_populates="collections")


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)
    user_id = Column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    set_num = Column(
        String,
        ForeignKey("sets.set_num", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    rating = Column(Float, nullable=True)
    text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "set_num", name="uq_reviews_user_set"),
        CheckConstraint(
            "(rating is null) or (rating >= 0.5 and rating <= 5.0)",
            name="reviews_rating_check",
        ),
        Index("ix_reviews_set_created", "set_num", "created_at"),
    )

    user = relationship("User", back_populates="reviews")
    set = relationship("Set", back_populates="reviews")
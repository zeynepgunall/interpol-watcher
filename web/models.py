from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from .config import WebConfig

Base = declarative_base()


class Notice(Base):
    """Interpol Red Notice row; is_updated=True means re-arrival alarm."""

    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    forename = Column(String(255), nullable=True)
    date_of_birth = Column(String(50), nullable=True)
    nationality = Column(String(255), nullable=True)
    all_nationalities = Column(String(1024), nullable=True)   # comma-separated, e.g. "DE,TR"
    arrest_warrant = Column(String(1024), nullable=True)
    thumbnail_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )
    is_updated = Column(Boolean, default=False, nullable=False)


def create_session_factory(config: WebConfig):
    # Auto-create the directory for SQLite databases so the app works out of the box
    if config.database_url.startswith("sqlite:///"):
        db_path = config.database_url[len("sqlite:///"):]
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
    engine = create_engine(config.database_url, echo=False, future=True)
    Base.metadata.create_all(engine)
    _ensure_columns(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def _ensure_columns(engine) -> None:
    """
    Lightweight schema migration: add any columns that exist in the ORM model
    but are absent from the live table (e.g. when upgrading an existing volume).

    Uses raw PRAGMA so it works without a full Alembic setup.
    Only handles new nullable columns — not renames or type changes.
    """
    import sqlalchemy

    with engine.connect() as conn:
        # Only implemented for SQLite; skip for other engines
        if not engine.dialect.name == "sqlite":
            return
        result = conn.execute(sqlalchemy.text("PRAGMA table_info(notices)"))
        existing = {row[1] for row in result.fetchall()}

    additions = {
        "all_nationalities": "TEXT DEFAULT NULL",
        "thumbnail_url":     "VARCHAR(512) DEFAULT NULL",
    }
    with engine.connect() as conn:
        for col, coldef in additions.items():
            if col not in existing:
                conn.execute(sqlalchemy.text(f"ALTER TABLE notices ADD COLUMN {col} {coldef}"))
                conn.commit()


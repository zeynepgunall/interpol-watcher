from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta

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

# Alarm'ın aktif kalacağı süre (saniye)
ALARM_WINDOW_SECONDS = 60


class Notice(Base):
    """Interpol Red Notice row; is_updated=True means re-arrival alarm."""

    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    forename = Column(String(255), nullable=True)
    date_of_birth = Column(String(50), nullable=True)
    nationality = Column(String(255), nullable=True)
    all_nationalities = Column(String(1024), nullable=True)
    arrest_warrant = Column(String(1024), nullable=True)
    photo_url = Column(String(512), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None), nullable=False)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        onupdate=lambda: datetime.now(timezone.utc).replace(tzinfo=None),
        nullable=False,
    )
    is_updated = Column(Boolean, default=False, nullable=False)

    @property
    def is_alarm_active(self) -> bool:
        """
        is_updated=True ve son güncelleme 60 saniyeden yeni ise True döner.
        Sweeper bu süre dolduktan sonra is_updated=False yapar.
        Böylece alarm kalıcı değil, geçici bir bildirim olur.
        """
        if not self.is_updated or self.updated_at is None:
            return False
        elapsed = datetime.now(timezone.utc) - self.updated_at.replace(tzinfo=timezone.utc)
        return elapsed.total_seconds() <= ALARM_WINDOW_SECONDS


def create_session_factory(config: WebConfig):
    """Config'deki DATABASE_URL ile SQLAlchemy engine oluşturur, tabloları yaratır ve sessionmaker döndürür."""
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
    """Lightweight schema migration: yeni kolonları mevcut tabloya ekler."""
    import sqlalchemy

    with engine.connect() as conn:
        if not engine.dialect.name == "sqlite":
            return
        result = conn.execute(sqlalchemy.text("PRAGMA table_info(notices)"))
        existing = {row[1] for row in result.fetchall()}

    additions = {
        "all_nationalities": "TEXT DEFAULT NULL",
        "photo_url":         "VARCHAR(512) DEFAULT NULL",
    }
    with engine.connect() as conn:
        for col, coldef in additions.items():
            if col not in existing:
                conn.execute(sqlalchemy.text(f"ALTER TABLE notices ADD COLUMN {col} {coldef}"))
                conn.commit()
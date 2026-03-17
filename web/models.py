"""SQLAlchemy ORM modelleri ve veritabanı oturum yönetimi."""
from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

from shared.utils import utcnow_naive
from .config import WebConfig

Base = declarative_base()

ALARM_WINDOW_SECONDS = 60


class Notice(Base):
    __tablename__ = "notices"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    entity_id         = Column(String(255), unique=True, nullable=False, index=True)
    name              = Column(String(255), nullable=True)
    forename          = Column(String(255), nullable=True)
    date_of_birth     = Column(String(50),  nullable=True)
    nationality       = Column(String(255), nullable=True)
    all_nationalities = Column(String(1024), nullable=True)
    arrest_warrant    = Column(String(1024), nullable=True)
    photo_url         = Column(String(512), nullable=True)
    created_at        = Column(DateTime, default=utcnow_naive, nullable=False)
    updated_at        = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False)
    is_updated        = Column(Boolean, default=False, nullable=False)

    charges              = Column(Text,        nullable=True)
    charge_translation   = Column(Text,        nullable=True)
    issuing_countries    = Column(String(512), nullable=True)
    place_of_birth       = Column(String(255), nullable=True)
    country_of_birth_id  = Column(String(10),  nullable=True)
    sex_id               = Column(String(5),   nullable=True)
    height               = Column(Float,       nullable=True)
    weight               = Column(Integer,     nullable=True)
    eyes_colors_id       = Column(String(64),  nullable=True)
    hairs_id             = Column(String(64),  nullable=True)
    languages_spoken     = Column(String(256), nullable=True)
    distinguishing_marks = Column(Text,        nullable=True)
    image_urls           = Column(Text,        nullable=True)
    detail_fetched_at    = Column(DateTime,    nullable=True)

    # İlişki: Bu notice'a ait tüm değişiklik kayıtları
    changes = relationship(
        "NoticeChange",
        back_populates="notice",
        order_by="NoticeChange.changed_at.desc()", # Değişiklikleri en yeniden eskiye sıralar
        lazy="dynamic",
    )

    @property
    def is_alarm_active(self) -> bool:
        if not self.is_updated or self.updated_at is None:
            return False
        elapsed = utcnow_naive() - self.updated_at
        return elapsed.total_seconds() <= ALARM_WINDOW_SECONDS


class NoticeChange(Base):
    """Bir notice kaydında tespit edilen her alan değişikliği buraya kaydedilir."""

    __tablename__ = "notice_changes"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    entity_id  = Column(String(255), ForeignKey("notices.entity_id", ondelete="CASCADE"), nullable=False, index=True)
    field_name = Column(String(100), nullable=False)
    old_value  = Column(Text, nullable=True)
    new_value  = Column(Text, nullable=True)
    changed_at = Column(DateTime, default=utcnow_naive, nullable=False)

    notice = relationship("Notice", back_populates="changes")

# İndeksleri kontrol eder ve oluşturur.
def _ensure_indexes(engine) -> None:
    statements = (
        "CREATE INDEX IF NOT EXISTS ix_notices_is_updated_created_at ON notices (is_updated, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_notices_is_updated_name_forename ON notices (is_updated, name, forename)",
        "CREATE INDEX IF NOT EXISTS ix_notices_created_at ON notices (created_at)",
        "CREATE INDEX IF NOT EXISTS ix_notices_name ON notices (name)",
        "CREATE INDEX IF NOT EXISTS ix_notices_forename ON notices (forename)",
        "CREATE INDEX IF NOT EXISTS ix_notices_nationality ON notices (nationality)",
        "CREATE INDEX IF NOT EXISTS ix_notice_changes_entity_id ON notice_changes (entity_id)",
        "CREATE INDEX IF NOT EXISTS ix_notice_changes_changed_at ON notice_changes (changed_at)",
    )
    with engine.begin() as conn:
        for statement in statements:
            conn.execute(text(statement))

# Veritabanı oturum  oluşturur.
def create_session_factory(config: WebConfig) -> sessionmaker:
    engine = create_engine(config.database_url, echo=False, future=True)
    Base.metadata.create_all(engine)
    _ensure_indexes(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


@contextmanager
def get_session(factory: sessionmaker):
    session = factory()
    try:
        yield session
    finally:
        session.close()
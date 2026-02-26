from __future__ import annotations

from datetime import datetime

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
    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    entity_id = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    forename = Column(String(255), nullable=True)
    date_of_birth = Column(String(50), nullable=True)
    nationality = Column(String(255), nullable=True)
    arrest_warrant = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    is_updated = Column(Boolean, default=False, nullable=False)


def create_session_factory(config: WebConfig):
    engine = create_engine(config.database_url, echo=False, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


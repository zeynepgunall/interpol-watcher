"""SQLAlchemy ORM modelleri ve veritabanı oturum yönetimi."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import timezone, timedelta

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from shared.utils import utcnow_naive
from .config import WebConfig

Base = declarative_base()

# Alarm süresi: güncellenen kayıt bu süre boyunca "aktif alarm" olarak gösterilir
ALARM_WINDOW_SECONDS = 60


class Notice(Base):
    """Interpol Red Notice kaydı. Interpol API'den gelen veriler bu modele dönüştürülür ve veritabanında saklanır."""

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
    created_at = Column(DateTime, default=utcnow_naive, nullable=False) #Kayıt oluşturulma zamanı
    updated_at = Column(DateTime, default=utcnow_naive, onupdate=utcnow_naive, nullable=False) #Kayıt güncellenme zamanı, her güncellemede otomatik olarak güncellenir
    is_updated = Column(Boolean, default=False, nullable=False)

    @property
    def is_alarm_active(self) -> bool:
        """Alarm penceresi 60sn'den azsa True döner."""
        if not self.is_updated or self.updated_at is None:
            return False
        elapsed = utcnow_naive() - self.updated_at
        return elapsed.total_seconds() <= ALARM_WINDOW_SECONDS


def create_session_factory(config: WebConfig) -> sessionmaker:
    """Database bağlantısı oluşturuyor ve session factory'si döndürüyor."""
    engine = create_engine(config.database_url, echo=False, future=True) #tablo yoksa otomatik oluşturur
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session) #yeni database oturumları oluşturmak için factory döner


@contextmanager
def get_session(factory: sessionmaker):
    """Oturum açıp işlem sonrası otomatik kapatan context manager.İşlem bitince otomatik kapatıyor"""
    session = factory()
    try:
        yield session
    finally:
        session.close()

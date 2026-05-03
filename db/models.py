from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime, timezone
from typing import Optional

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    __mapper_args__ = {"eager_defaults": True}
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="bot")  # "bot" или "web"
    
    # VPN подписка (для бота)
    vpn_subscription_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    bypass_subscription_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    vpn_client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # NeuroPrompt подписка
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    expiry_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Платежи Yookassa
    yookassa_payment_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    yookassa_customer_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    payment_method_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Техническое
    last_reminder_sent: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Восстановление пароля (для веб-пользователей)
    reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reset_token_expires: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

class Client(Base):
    __tablename__ = "clients"
    client_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class PaymentLog(Base):
    __tablename__ = "payment_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String, unique=True, nullable=False, index=True)
    telegram_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, String, DateTime, Boolean, Index
from datetime import datetime
from typing import Optional

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, index=True, nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="bot")  # "bot" или "web"
    
    # VPN подписка
    vpn_subscription_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    bypass_subscription_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    vpn_client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # NeuroPrompt подписка
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expiry_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Платежи Yookassa
    yookassa_payment_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    yookassa_customer_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    payment_method_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Техническое
    last_reminder_sent: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

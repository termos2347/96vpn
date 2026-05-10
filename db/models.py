from sqlalchemy import Column, Integer, BigInteger, String, DateTime, Boolean, Float, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from datetime import datetime, timezone
from typing import Optional

class Base(DeclarativeBase):
    pass

# ---------- Веб-пользователь ----------
class WebUser(Base):
    __tablename__ = "web_users"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    # Восстановление пароля
    reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    reset_token_expires: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Подписка NeuroPrompt
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    expiry_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Платежи Yookassa
    yookassa_payment_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    yookassa_customer_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    payment_method_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# ---------- Бот-пользователь ----------
class BotUser(Base):
    __tablename__ = "bot_users"
    __mapper_args__ = {"eager_defaults": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # VPN подписка
    vpn_subscription_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    bypass_subscription_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    vpn_client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    server_id: Mapped[Optional[int]] = mapped_column(ForeignKey("vpn_servers.id"), nullable=True)   # <-- новый внешний ключ

    last_reminder_sent: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


# ---------- Платёжные логи бота ----------
class BotPayment(Base):
    __tablename__ = "bot_payments"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    payment_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ---------- Категории и промпты ----------
class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Prompt(Base):
    __tablename__ = "prompts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    content: Mapped[str] = mapped_column(String(5000), nullable=False)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False)
    is_free: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    category = relationship("Category", backref="prompts")


# ---------- VPN-серверы ----------
class VPNServer(Base):
    __tablename__ = "vpn_servers"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(nullable=False)
    inbound_id: Mapped[int] = mapped_column(nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    api_path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sub_port: Mapped[int] = mapped_column(Integer, nullable=False, default=2096)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    weight: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

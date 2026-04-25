from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, String, DateTime
from datetime import datetime
from typing import Optional

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    vpn_subscription_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    bypass_subscription_end: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    vpn_client_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_reminder_sent: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

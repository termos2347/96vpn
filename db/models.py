from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, String, DateTime
from datetime import datetime

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"
    
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(100), nullable=True)
    
    # Подписка на VPN
    vpn_subscription_end: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    # Подписка на обход блокировок
    bypass_subscription_end: Mapped[datetime] = mapped_column(DateTime, nullable=True)
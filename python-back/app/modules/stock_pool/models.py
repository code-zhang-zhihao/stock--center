from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def created_at_column():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at_column():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class StockPool(Base):
    __tablename__ = "t_stock_pool"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pool_code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    pool_name: Mapped[str] = mapped_column(String(160), nullable=False)
    pool_type: Mapped[str] = mapped_column(String(40), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_dynamic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dynamic_rule: Mapped[str | None] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class StockPoolMember(Base):
    __tablename__ = "t_stock_pool_member"
    __table_args__ = (UniqueConstraint("pool_id", "stock_code", name="uq_t_stock_pool_member_pool_stock"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("t_stock_pool.id", ondelete="CASCADE"), nullable=False)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

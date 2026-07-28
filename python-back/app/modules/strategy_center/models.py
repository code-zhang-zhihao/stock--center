from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StrategyDefinition(Base):
    __tablename__ = "t_strategy_definition"
    __table_args__ = (UniqueConstraint("strategy_code", name="uq_t_strategy_definition_code"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_code: Mapped[str] = mapped_column(String(60), nullable=False)
    strategy_name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    strategy_type: Mapped[str] = mapped_column(String(40), nullable=False, default="short_term")
    entry_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="auction")
    max_holding_trade_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    rule_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risk_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    pool_id: Mapped[int | None] = mapped_column(ForeignKey("t_stock_pool.id", ondelete="SET NULL"), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class StrategyCandidate(Base):
    __tablename__ = "t_strategy_candidate"
    __table_args__ = (
        UniqueConstraint("strategy_id", "signal_trade_date", "stock_code", name="uq_t_strategy_candidate_business"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("t_strategy_definition.id", ondelete="CASCADE"), nullable=False)
    signal_trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    candidate_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending_confirmation")
    score: Mapped[float | None] = mapped_column(Float)
    rank_no: Mapped[int | None] = mapped_column(Integer)
    confirmation_deadline: Mapped[date | None] = mapped_column(Date)
    candidate_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    entry_plan: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    outcome_note: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class StrategyPaperTrade(Base):
    __tablename__ = "t_strategy_paper_trade"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("t_strategy_candidate.id", ondelete="RESTRICT"), nullable=False, unique=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("t_strategy_definition.id", ondelete="RESTRICT"), nullable=False)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    entry_amount: Mapped[float | None] = mapped_column(Float)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exit_price: Mapped[float | None] = mapped_column(Float)
    exit_amount: Mapped[float | None] = mapped_column(Float)
    realized_pnl_amount: Mapped[float | None] = mapped_column(Float)
    realized_pnl_pct: Mapped[float | None] = mapped_column(Float)
    entry_evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    exit_evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risk_plan: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

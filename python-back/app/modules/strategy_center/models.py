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
        UniqueConstraint(
            "strategy_version_id",
            "signal_trade_date",
            "stock_code",
            name="uq_t_strategy_candidate_version_business",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("t_strategy_definition.id", ondelete="CASCADE"), nullable=False)
    strategy_version_id: Mapped[int] = mapped_column(
        ForeignKey("t_strategy_version.id", ondelete="RESTRICT"), nullable=False
    )
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
    initial_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    open_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
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


class StrategyVersion(Base):
    __tablename__ = "t_strategy_version"
    __table_args__ = (UniqueConstraint("strategy_id", "version_no", name="uq_t_strategy_version_business"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("t_strategy_definition.id", ondelete="CASCADE"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    implementation_code: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft")
    rule_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    risk_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    validation_summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class StrategySignalEvent(Base):
    __tablename__ = "t_strategy_signal_event"
    __table_args__ = (UniqueConstraint("event_fingerprint", name="uq_t_strategy_signal_event_fingerprint"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("t_strategy_definition.id", ondelete="CASCADE"), nullable=False)
    strategy_version_id: Mapped[int] = mapped_column(
        ForeignKey("t_strategy_version.id", ondelete="RESTRICT"), nullable=False
    )
    candidate_id: Mapped[int | None] = mapped_column(ForeignKey("t_strategy_candidate.id", ondelete="CASCADE"))
    paper_trade_id: Mapped[int | None] = mapped_column(ForeignKey("t_strategy_paper_trade.id", ondelete="SET NULL"))
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    market_phase: Mapped[str] = mapped_column(String(24), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    decision: Mapped[str] = mapped_column(String(24), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100))
    event_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StrategyPaperTradeLeg(Base):
    __tablename__ = "t_strategy_paper_trade_leg"
    __table_args__ = (UniqueConstraint("paper_trade_id", "leg_no", name="uq_t_strategy_paper_trade_leg_business"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    paper_trade_id: Mapped[int] = mapped_column(
        ForeignKey("t_strategy_paper_trade.id", ondelete="CASCADE"), nullable=False
    )
    leg_no: Mapped[int] = mapped_column(Integer, nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    execution_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[float | None] = mapped_column(Float)
    trigger_code: Mapped[str] = mapped_column(String(100), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class StrategyBacktestRun(Base):
    __tablename__ = "t_strategy_backtest_run"
    __table_args__ = (UniqueConstraint("run_code", name="uq_t_strategy_backtest_run_code"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_code: Mapped[str] = mapped_column(String(64), nullable=False)
    strategy_id: Mapped[int] = mapped_column(ForeignKey("t_strategy_definition.id", ondelete="CASCADE"), nullable=False)
    strategy_version_id: Mapped[int] = mapped_column(
        ForeignKey("t_strategy_version.id", ondelete="RESTRICT"), nullable=False
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    execution_model: Mapped[str] = mapped_column(String(40), nullable=False, default="next_open_daily")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    fee_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0005)
    slippage_bps: Mapped[float] = mapped_column(Float, nullable=False, default=10)
    parameter_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class StrategyBacktestTrade(Base):
    __tablename__ = "t_strategy_backtest_trade"
    __table_args__ = (
        UniqueConstraint("backtest_run_id", "stock_code", "signal_trade_date", name="uq_t_strategy_backtest_trade_business"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    backtest_run_id: Mapped[int] = mapped_column(
        ForeignKey("t_strategy_backtest_run.id", ondelete="CASCADE"), nullable=False
    )
    strategy_id: Mapped[int] = mapped_column(ForeignKey("t_strategy_definition.id", ondelete="CASCADE"), nullable=False)
    strategy_version_id: Mapped[int] = mapped_column(
        ForeignKey("t_strategy_version.id", ondelete="RESTRICT"), nullable=False
    )
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)
    signal_trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    exit_trade_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    exit_price: Mapped[float] = mapped_column(Float, nullable=False)
    gross_return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    net_return_pct: Mapped[float] = mapped_column(Float, nullable=False)
    holding_trade_days: Mapped[int] = mapped_column(Integer, nullable=False)
    exit_reason: Mapped[str] = mapped_column(String(100), nullable=False)
    candidate_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    execution_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

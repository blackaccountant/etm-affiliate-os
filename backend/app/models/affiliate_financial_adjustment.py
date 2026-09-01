from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import CheckConstraint, ForeignKey, Integer, Numeric, String, UniqueConstraint, column
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base
from app.database.types import UTCDateTime

class AffiliateFinancialAdjustment(Base):
    __tablename__="affiliate_financial_adjustments"
    __table_args__=(UniqueConstraint("affiliate_program_id","source_namespace","source_event_digest",name="uq_affiliate_financial_adjustments_source"),CheckConstraint("adjustment_type IN ('REFUND','REVERSAL','CHARGEBACK','CLAWBACK','CANCELLATION','CORRECTION','RESTORATION')",name="ck_affiliate_financial_adjustments_type"),CheckConstraint("(adjustment_type IN ('REFUND','REVERSAL','CHARGEBACK','CLAWBACK','CANCELLATION') AND adjustment_amount < 0) OR (adjustment_type IN ('CORRECTION','RESTORATION') AND adjustment_amount > 0)",name="ck_affiliate_financial_adjustments_type_sign"),CheckConstraint("source_namespace ~ '^[a-z][a-z0-9.-]{0,62}$'",name="ck_affiliate_financial_adjustments_namespace"),CheckConstraint("source_event_digest ~ '^[0-9a-f]{64}$'",name="ck_affiliate_financial_adjustments_digest"),CheckConstraint("fingerprint ~ '^[0-9a-f]{64}$'",name="ck_affiliate_financial_adjustments_fingerprint"))
    id:Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid4()))
    affiliate_earning_id:Mapped[int]=mapped_column(Integer,ForeignKey("affiliate_earnings.id"),nullable=False)
    affiliate_program_id:Mapped[int]=mapped_column(Integer,ForeignKey("affiliate_programs.id"),nullable=False)
    affiliate_conversion_id:Mapped[int|None]=mapped_column(Integer,ForeignKey("affiliate_conversions.id"),nullable=True)
    affiliate_payout_id:Mapped[int|None]=mapped_column(Integer,ForeignKey("affiliate_payouts.id"),nullable=True)
    attribution_payout_settlement_link_id:Mapped[str|None]=mapped_column(String(36),ForeignKey("attribution_payout_settlement_links.id"),nullable=True)
    adjustment_type:Mapped[str]=mapped_column(String(32),nullable=False); adjustment_amount:Mapped[object]=mapped_column(Numeric(18,2),nullable=False); currency:Mapped[str]=mapped_column(String(3),nullable=False)
    effective_at:Mapped[datetime]=mapped_column(UTCDateTime(),nullable=False); source_namespace:Mapped[str]=mapped_column(String(63),nullable=False); source_event_digest:Mapped[str]=mapped_column(String(64),nullable=False); fingerprint:Mapped[str]=mapped_column(String(64),nullable=False); recorded_at:Mapped[datetime]=mapped_column(UTCDateTime(),nullable=False,default=lambda:datetime.now(timezone.utc))

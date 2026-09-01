from sqlalchemy import text, func
from app.models.affiliate_financial_adjustment import AffiliateFinancialAdjustment
from app.models.affiliate_earning import AffiliateEarning
from app.models.attribution_payout_settlement_link import AttributionPayoutSettlementLink
class AffiliateFinancialAdjustmentRepository:
 def __init__(self,db): self.db=db
 def lock_earning(self,id): return self.db.query(AffiliateEarning).filter_by(id=id).with_for_update().one_or_none()
 def lock(self,id):
  if self.db.bind.dialect.name=="postgresql": self.db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:v,0))"),{"v":f"m10a7:{id}"})
 def source(self,p,n,d): return self.db.query(AffiliateFinancialAdjustment).filter_by(affiliate_program_id=p,source_namespace=n,source_event_digest=d).one_or_none()
 def total(self,e): return self.db.query(func.coalesce(func.sum(AffiliateFinancialAdjustment.adjustment_amount),0)).filter_by(affiliate_earning_id=e).scalar()
 def settlement(self,id): return self.db.query(AttributionPayoutSettlementLink).filter_by(id=id).with_for_update().one_or_none()

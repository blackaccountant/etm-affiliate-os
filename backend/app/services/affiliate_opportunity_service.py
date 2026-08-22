"""
Affiliate Opportunity Service

Handles creation and updates of affiliate opportunity records.
"""

from sqlalchemy.orm import Session

from app.models.affiliate_opportunity import (
    AffiliateOpportunity,
)

from app.schemas.affiliate_opportunity import (
    AffiliateOpportunitySchema,
)



class AffiliateOpportunityService:


    def __init__(
        self,
        db: Session,
    ):
        self.db = db



    def save_opportunity(
        self,
        product_id: int,
        opportunity: AffiliateOpportunitySchema,
    ):

        """
        Save or update affiliate opportunity.
        """


        existing = (
            self.db.query(
                AffiliateOpportunity
            )
            .filter(
                AffiliateOpportunity.product_id
                == product_id
            )
            .first()
        )


        if existing:

            existing.opportunity_grade = (
                opportunity.opportunity_grade
            )

            existing.audience = (
                self._serialize(
                    opportunity.audience
                )
            )

            existing.content_strategy = (
                self._serialize(
                    opportunity.content_strategy
                )
            )

            existing.seo_keywords = (
                self._serialize(
                    opportunity.seo_keywords
                )
            )

            existing.promotion_channels = (
                self._serialize(
                    opportunity.promotion_channels
                )
            )

            existing.funnel_strategy = (
                self._serialize(
                    opportunity.funnel_strategy
                )
            )

            existing.revenue_projection = (
                self._serialize(
                    opportunity.revenue_projection
                )
            )

            existing.ai_recommendation = (
                opportunity.ai_recommendation
            )

            existing.confidence = (
                opportunity.confidence
            )


            existing.status = "active"


            self.db.commit()

            self.db.refresh(
                existing
            )

            return existing



        record = AffiliateOpportunity(

            product_id=product_id,

            opportunity_grade=(
                opportunity.opportunity_grade
            ),

            audience=(
                self._serialize(
                    opportunity.audience
                )
            ),

            content_strategy=(
                self._serialize(
                    opportunity.content_strategy
                )
            ),

            seo_keywords=(
                self._serialize(
                    opportunity.seo_keywords
                )
            ),

            promotion_channels=(
                self._serialize(
                    opportunity.promotion_channels
                )
            ),

            funnel_strategy=(
                self._serialize(
                    opportunity.funnel_strategy
                )
            ),

            revenue_projection=(
                self._serialize(
                    opportunity.revenue_projection
                )
            ),

            ai_recommendation=(
                opportunity.ai_recommendation
            ),

            confidence=(
                opportunity.confidence
            ),

            status="active",

        )


        self.db.add(
            record
        )

        self.db.commit()

        self.db.refresh(
            record
        )


        return record



    def _serialize(
        self,
        value,
    ):

        if value is None:
            return None


        if isinstance(
            value,
            str,
        ):
            return value


        return str(
            value
        )
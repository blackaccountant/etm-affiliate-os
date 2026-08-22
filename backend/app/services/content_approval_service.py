"""
Content Approval Service

Evaluates generated content and decides
whether it is ready for publishing.

Rules:

80+  -> approved
60-79 -> needs_revision
below 60 -> rejected
"""


import logging

from sqlalchemy.orm import Session

from app.models.content_approval import ContentApproval

from app.models.content_seo_score import ContentSEOScore

from app.models.affiliate_content_asset import (
    AffiliateContentAsset,
)


logger = logging.getLogger(__name__)


class ContentApprovalService:


    def __init__(
        self,
        db: Session,
    ):
        self.db = db



    def evaluate(
        self,
        content_asset_id: int,
    ) -> ContentApproval:


        asset = (
            self.db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.id == content_asset_id
            )
            .first()
        )


        if not asset:

            raise ValueError(
                f"Content asset {content_asset_id} not found"
            )



        seo_score = (
            self.db.query(
                ContentSEOScore
            )
            .filter(
                ContentSEOScore.content_asset_id
                ==
                content_asset_id
            )
            .order_by(
                ContentSEOScore.id.desc()
            )
            .first()
        )


        if not seo_score:

            raise ValueError(
                "SEO score not found"
            )



        score = seo_score.overall_score



        if score >= 80:

            decision = "approved"

            reason = (
                "SEO score meets publishing threshold."
            )


        elif score >= 60:

            decision = "needs_revision"

            reason = (
                "Content requires SEO improvements."
            )


        else:

            decision = "rejected"

            reason = (
                "Content quality below minimum threshold."
            )



        # Prevent duplicate approvals
        existing = (
            self.db.query(
                ContentApproval
            )
            .filter(
                ContentApproval.content_asset_id
                ==
                content_asset_id
            )
            .order_by(
                ContentApproval.id.desc()
            )
            .first()
        )


        if existing:

            logger.info(
                "Updating existing approval record for asset %s",
                content_asset_id
            )

            existing.decision = decision
            existing.reason = reason
            existing.score = score

            approval = existing


        else:

            approval = ContentApproval(
                content_asset_id=content_asset_id,
                decision=decision,
                reason=reason,
                score=score,
            )

            self.db.add(
                approval
            )



        # Update asset lifecycle state

        if decision == "approved":

            asset.status = "approved"


        elif decision == "needs_revision":

            asset.status = "seo_review"


        else:

            asset.status = "rejected"



        try:

            self.db.commit()

            self.db.refresh(
                approval
            )

        except Exception:

            self.db.rollback()

            logger.exception(
                "Approval transaction failed"
            )

            raise



        logger.info(
            "Content approval completed asset=%s decision=%s score=%s",
            content_asset_id,
            decision,
            score,
        )


        return approval
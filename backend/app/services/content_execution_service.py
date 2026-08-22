"""
Content Execution Service

Runs content assets through:
1. Content Writer Agent
2. Database persistence
3. SEO Optimization

Production pipeline:
generated -> seo_review
"""


from sqlalchemy.orm import Session


from app.models.affiliate_content_asset import (
    AffiliateContentAsset,
)


from app.services.content_writer_agent import (
    ContentWriterAgent,
)


from app.services.seo_optimizer_service import (
    SEOOptimizerService,
)


from app.services.content_approval_service import (
    ContentApprovalService,
)



class ContentExecutionService:


    def __init__(
        self,
        db: Session,
    ):

        self.db = db

        self.writer = ContentWriterAgent()

        self.seo_optimizer = SEOOptimizerService(
            db
        )

        self.approval_service = ContentApprovalService(
            db
        )



    def generate_content(
        self,
        asset_id: int,
    ):


        asset = (
            self.db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.id == asset_id
            )
            .first()
        )


        if not asset:

            raise ValueError(
                "Content asset not found"
            )


        #
        # Generation stage
        #

        asset.status = "generating"

        self.db.commit()



        result = self.writer.generate(
            asset
        )



        asset.generated_content = (
            result.get(
                "content",
                ""
            )
        )


        asset.seo_title = (
            result.get(
                "seo_title",
                asset.title
            )
        )


        asset.seo_description = (
            result.get(
                "seo_description",
                ""
            )
        )


        asset.status = "generated"



        self.db.commit()


        self.db.refresh(
            asset
        )



        #
        # SEO Analysis stage
        #

        seo_score = (
            self.seo_optimizer.analyze_content(
                content_asset_id=asset.id
            )
        )


        approval = (
            self.approval_service.evaluate(
                content_asset_id=asset.id
            )
        )



        asset.status = (
            "seo_review"
        )


        self.db.commit()


        self.db.refresh(
            asset
        )



        return {

            "asset": asset,

            "seo_score": seo_score,

            "approval": approval

        }

"""
Publisher Service

Responsible for moving approved content
from publishing queue to published state.
"""


from datetime import datetime

from sqlalchemy.orm import Session

from app.models.publishing_queue import PublishingQueue
from app.models.affiliate_content_asset import AffiliateContentAsset


class PublisherService:


    def __init__(self, db: Session):

        self.db = db



    def publish(
        self,
        queue_id: int
    ):

        queue_item = (
            self.db.query(
                PublishingQueue
            )
            .filter(
                PublishingQueue.id == queue_id
            )
            .first()
        )


        if not queue_item:

            raise ValueError(
                "Publishing queue item not found"
            )



        asset = (
            self.db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.id
                ==
                queue_item.content_asset_id
            )
            .first()
        )


        if not asset:

            raise ValueError(
                "Content asset not found"
            )



        queue_item.status = "publishing"


        self.db.commit()



        # Internal publisher simulation
        published_url = (
            f"https://etm-affiliate-os.local/content/{asset.id}"
        )


        queue_item.status = "published"

        queue_item.published_url = (
            published_url
        )

        queue_item.published_at = (
            datetime.utcnow()
        )


        asset.status = "published"

        asset.published_url = (
            published_url
        )


        self.db.commit()

        self.db.refresh(queue_item)


        return queue_item
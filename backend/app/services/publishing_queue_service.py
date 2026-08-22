"""
Publishing Queue Service

Moves approved content assets
into the publishing pipeline.
"""


import logging

from sqlalchemy.orm import Session

from app.models.publishing_queue import PublishingQueue

from app.models.affiliate_content_asset import (
    AffiliateContentAsset,
)


logger = logging.getLogger(__name__)


class PublishingQueueService:


    def __init__(
        self,
        db: Session,
    ):

        self.db = db



    def queue_content(
        self,
        content_asset_id: int,
        channel: str = "internal",
    ):


        asset = (
            self.db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.id
                ==
                content_asset_id
            )
            .first()
        )


        if not asset:

            raise ValueError(
                "Content asset not found"
            )



        if asset.status != "approved":

            raise ValueError(
                f"Content asset is not approved. Current status: {asset.status}"
            )



        existing = (
            self.db.query(
                PublishingQueue
            )
            .filter(
                PublishingQueue.content_asset_id
                ==
                content_asset_id
            )
            .first()
        )


        if existing:

            return existing



        queue_item = PublishingQueue(

            content_asset_id=content_asset_id,

            status="pending",

            channel=channel,

        )


        self.db.add(
            queue_item
        )


        self.db.commit()


        self.db.refresh(
            queue_item
        )


        logger.info(
            "Content %s added to publishing queue",
            content_asset_id,
        )


        return queue_item
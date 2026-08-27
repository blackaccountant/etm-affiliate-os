"""
Publisher Service

Responsible for moving approved content
from publishing queue to published state.

Publishing is idempotent:
- A published queue item is never published again.
- Existing published_url and published_at are preserved.
"""


from datetime import datetime

from sqlalchemy.orm import Session

from app.models.publishing_queue import PublishingQueue
from app.models.affiliate_content_asset import AffiliateContentAsset


class PublisherService:

    def __init__(
        self,
        db: Session,
    ):
        self.db = db

    # =========================================================
    # PUBLISH
    # =========================================================

    def publish(
        self,
        queue_id: int,
    ):

        # -----------------------------------------------------
        # Load queue item
        # -----------------------------------------------------

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

        # -----------------------------------------------------
        # Idempotency protection
        #
        # If this item has already been published,
        # return it unchanged.
        # -----------------------------------------------------

        if queue_item.status == "published":

            return queue_item

        # -----------------------------------------------------
        # Load content asset
        # -----------------------------------------------------

        asset = (
            self.db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.id
                == queue_item.content_asset_id
            )
            .first()
        )

        if not asset:

            raise ValueError(
                "Content asset not found"
            )

        # -----------------------------------------------------
        # Validate asset state
        # -----------------------------------------------------

        if asset.status not in (
            "approved",
            "publishing",
        ):

            raise ValueError(
                "Content asset is not approved for publishing"
            )

        # -----------------------------------------------------
        # Mark queue item as publishing
        # -----------------------------------------------------

        queue_item.status = "publishing"

        self.db.commit()

        # -----------------------------------------------------
        # Internal publisher simulation
        # -----------------------------------------------------

        published_url = (
            f"https://etm-affiliate-os.local/content/{asset.id}"
        )

        # -----------------------------------------------------
        # Complete publication
        # -----------------------------------------------------

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

        # -----------------------------------------------------
        # Persist publication
        # -----------------------------------------------------

        self.db.commit()

        self.db.refresh(
            queue_item
        )

        return queue_item
"""
Publishing Queue Service

Handles creation and retrieval of publishing queue jobs.

Publishing is idempotent per:

    content_asset_id + channel

This allows the same content asset to be distributed
to multiple channels while preventing duplicate jobs
for the same asset/channel combination.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.models.affiliate_content_asset import AffiliateContentAsset
from app.models.publishing_queue import PublishingQueue


class PublishingQueueService:

    def __init__(
        self,
        db: Session,
    ):
        self.db = db

    # =========================================================
    # QUEUE CONTENT
    # =========================================================

    def queue_content(
        self,
        content_asset_id: int,
        channel: str = "internal",
        scheduled_at=None,
    ) -> PublishingQueue:

        # -----------------------------------------------------
        # Validate content asset
        # -----------------------------------------------------

        asset = (
            self.db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.id
                == content_asset_id
            )
            .first()
        )

        if not asset:

            raise ValueError(
                f"Content asset {content_asset_id} "
                f"does not exist."
            )

        # -----------------------------------------------------
        # Normalize channel
        # -----------------------------------------------------

        channel = (
            str(channel)
            .strip()
            .lower()
        )

        if not channel:

            raise ValueError(
                "Publishing channel cannot be empty."
            )

        # -----------------------------------------------------
        # Idempotency check
        #
        # One queue record per:
        #
        #     content_asset_id + channel
        #
        # -----------------------------------------------------

        existing = (
            self.db.query(
                PublishingQueue
            )
            .filter(
                PublishingQueue.content_asset_id
                == content_asset_id,
                PublishingQueue.channel
                == channel,
            )
            .first()
        )

        if existing:

            return existing

        # -----------------------------------------------------
        # Create queue item
        # -----------------------------------------------------

        queue_item = PublishingQueue(

            content_asset_id=(
                content_asset_id
            ),

            status="pending",

            channel=channel,

            scheduled_at=scheduled_at,

        )

        self.db.add(
            queue_item
        )

        self.db.flush()

        self.db.refresh(
            queue_item
        )

        return queue_item

    # =========================================================
    # GET QUEUE ITEM
    # =========================================================

    def get_queue_item(
        self,
        content_asset_id: int,
        channel: str = "internal",
    ) -> Optional[PublishingQueue]:

        channel = (
            str(channel)
            .strip()
            .lower()
        )

        return (
            self.db.query(
                PublishingQueue
            )
            .filter(
                PublishingQueue.content_asset_id
                == content_asset_id,
                PublishingQueue.channel
                == channel,
            )
            .first()
        )

    # =========================================================
    # GET BY ID
    # =========================================================

    def get_by_id(
        self,
        queue_id: int,
    ) -> Optional[PublishingQueue]:

        return (
            self.db.query(
                PublishingQueue
            )
            .filter(
                PublishingQueue.id
                == queue_id
            )
            .first()
        )

    # =========================================================
    # MARK PUBLISHED
    # =========================================================

    def mark_published(
        self,
        queue_id: int,
        published_url: str | None = None,
    ) -> PublishingQueue:

        queue_item = self.get_by_id(
            queue_id
        )

        if not queue_item:

            raise ValueError(
                f"Publishing queue item "
                f"{queue_id} does not exist."
            )

        from datetime import datetime

        queue_item.status = "published"

        queue_item.published_url = (
            published_url
        )

        queue_item.published_at = (
            datetime.utcnow()
        )

        self.db.flush()

        self.db.refresh(
            queue_item
        )

        return queue_item

    # =========================================================
    # MARK FAILED
    # =========================================================

    def mark_failed(
        self,
        queue_id: int,
    ) -> PublishingQueue:

        queue_item = self.get_by_id(
            queue_id
        )

        if not queue_item:

            raise ValueError(
                f"Publishing queue item "
                f"{queue_id} does not exist."
            )

        queue_item.status = "failed"

        self.db.flush()

        self.db.refresh(
            queue_item
        )

        return queue_item
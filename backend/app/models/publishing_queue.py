from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)

from sqlalchemy.orm import relationship

from datetime import datetime

from app.database.base import Base


class PublishingQueue(Base):

    __tablename__ = "publishing_queue"


    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )


    content_asset_id = Column(
        Integer,
        ForeignKey(
            "affiliate_content_assets.id"
        ),
        nullable=False,
    )


    status = Column(
        String(50),
        default="pending",
        nullable=False,
    )


    channel = Column(
        String(100),
        default="internal",
    )


    published_url = Column(
        String(1000),
        nullable=True,
    )


    scheduled_at = Column(
        DateTime,
        nullable=True,
    )


    published_at = Column(
        DateTime,
        nullable=True,
    )


    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )


    content_asset = relationship(
        "AffiliateContentAsset",
        back_populates="publishing_queue",
    )


    __table_args__ = (
        UniqueConstraint(
            "content_asset_id",
            "channel",
            name="uq_publishing_queue_asset_channel",
        ),
    )
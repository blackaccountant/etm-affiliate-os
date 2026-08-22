"""
Affiliate Content Asset Model

Stores marketing assets generated
from affiliate opportunities.

Supports:
- Content lifecycle
- Version history
- Publishing state
"""

from datetime import datetime


from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Boolean,
)


from sqlalchemy.orm import relationship


from app.database.base import Base



class AffiliateContentAsset(Base):


    __tablename__ = "affiliate_content_assets"



    id = Column(
        Integer,
        primary_key=True,
        index=True,
    )


    product_id = Column(
        Integer,
        ForeignKey(
            "products.id"
        ),
        nullable=False,
        index=True,
    )


    # -------------------------
    # Version control
    # -------------------------

    parent_id = Column(
        Integer,
        ForeignKey(
            "affiliate_content_assets.id"
        ),
        nullable=True,
        index=True,
    )


    version = Column(
        Integer,
        nullable=False,
        default=1,
    )


    is_active = Column(
        Boolean,
        nullable=False,
        default=True,
    )



    # -------------------------
    # Content information
    # -------------------------

    asset_type = Column(
        String(100),
        nullable=False,
    )


    title = Column(
        String(500),
        nullable=False,
    )


    target_keyword = Column(
        String(500),
        nullable=True,
    )


    audience = Column(
        Text,
        nullable=True,
    )


    search_intent = Column(
        String(100),
        nullable=True,
    )


    content_outline = Column(
        Text,
        nullable=True,
    )



    call_to_action = Column(
        Text,
        nullable=True,
    )


    publishing_queue = relationship(
        "PublishingQueue",
        back_populates="content_asset",
    )



    # -------------------------
    # Execution lifecycle
    # -------------------------

    status = Column(
        String(50),
        nullable=False,
        default="planned",
        index=True,
    )


    generated_content = Column(
        Text,
        nullable=True,
    )


    seo_title = Column(
        String(500),
        nullable=True,
    )


    seo_description = Column(
        Text,
        nullable=True,
    )


    seo_scores = relationship(
        "ContentSEOScore",
        back_populates="content_asset",
    )


    published_url = Column(
        String(1000),
        nullable=True,
    )


    # -------------------------
    # Timestamps
    # -------------------------

    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )


    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )



    # -------------------------
    # Relationships
    # -------------------------

    product = relationship(
        "Product",
        back_populates="content_assets",
    )


    parent = relationship(
        "AffiliateContentAsset",
        remote_side=[id],
        backref="versions",
    )
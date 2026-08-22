from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    DateTime,
)

from sqlalchemy.orm import relationship
from datetime import datetime

from app.database.base import Base


class ContentSEOScore(Base):

    __tablename__ = "content_seo_scores"


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
        index=True,
    )


    keyword_score = Column(
        Integer,
        nullable=False,
        default=0,
    )


    search_intent_score = Column(
        Integer,
        nullable=False,
        default=0,
    )


    readability_score = Column(
        Integer,
        nullable=False,
        default=0,
    )


    content_depth_score = Column(
        Integer,
        nullable=False,
        default=0,
    )


    affiliate_fit_score = Column(
        Integer,
        nullable=False,
        default=0,
    )


    overall_score = Column(
        Integer,
        nullable=False,
        default=0,
    )


    recommendations = Column(
        Text,
        nullable=True,
    )


    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )


    content_asset = relationship(
        "AffiliateContentAsset",
        back_populates="seo_scores",
    )
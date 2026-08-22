"""
Affiliate Opportunity Model

Stores monetization strategy
generated from affiliate intelligence.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
)

from sqlalchemy.orm import relationship

from app.database.base import Base
from app.models.product import Product


class AffiliateOpportunity(Base):

    __tablename__ = "affiliate_opportunities"


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


    opportunity_grade = Column(
        String(50),
        nullable=False,
        default="UNKNOWN",
    )


    audience = Column(
        Text,
        nullable=True,
    )


    content_strategy = Column(
        Text,
        nullable=True,
    )


    seo_keywords = Column(
        Text,
        nullable=True,
    )


    promotion_channels = Column(
        Text,
        nullable=True,
    )


    funnel_strategy = Column(
        Text,
        nullable=True,
    )


    revenue_projection = Column(
        Text,
        nullable=True,
    )


    ai_recommendation = Column(
        Text,
        nullable=True,
    )


    confidence = Column(
        Integer,
        nullable=False,
        default=0,
    )


    status = Column(
        String(50),
        nullable=False,
        default="active",
    )


    created_at = Column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


    product = relationship(
        "Product",
        back_populates="affiliate_opportunities",
    )
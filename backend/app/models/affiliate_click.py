"""
Affiliate Click Model

Tracks visitor clicks
on affiliate links.
"""


from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)

from sqlalchemy.orm import relationship

from app.database.base import Base



class AffiliateClick(Base):

    __tablename__ = "affiliate_clicks"

    __table_args__ = (
        UniqueConstraint(
            "attribution_click_id",
            name="uq_affiliate_clicks_attribution_click_id",
        ),
    )


    id = Column(
        Integer,
        primary_key=True,
        index=True
    )


    affiliate_link_id = Column(
        Integer,
        ForeignKey(
            "affiliate_links.id"
        ),
        nullable=False
    )


    ip_address = Column(
        String(100),
        nullable=True
    )


    user_agent = Column(
        String(500),
        nullable=True
    )


    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


    affiliate_link = relationship(
        "AffiliateLink"
    )


    attribution_click_id = Column(
        String(36),
        ForeignKey("attribution_clicks.id"),
        nullable=True,
    )

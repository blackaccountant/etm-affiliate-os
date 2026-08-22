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
)

from sqlalchemy.orm import relationship

from app.database.base import Base



class AffiliateClick(Base):

    __tablename__ = "affiliate_clicks"


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
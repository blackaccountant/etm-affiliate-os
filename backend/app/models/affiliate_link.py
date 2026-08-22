"""
Affiliate Link Model

Stores affiliate URLs connected
to affiliate programs and content.
"""


from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Boolean,
    ForeignKey,
)

from sqlalchemy.orm import relationship

from app.database.base import Base



class AffiliateLink(Base):

    __tablename__ = "affiliate_links"


    id = Column(
        Integer,
        primary_key=True,
        index=True
    )


    affiliate_program_id = Column(
        Integer,
        ForeignKey(
            "affiliate_programs.id"
        ),
        nullable=False
    )


    content_asset_id = Column(
        Integer,
        ForeignKey(
            "affiliate_content_assets.id"
        ),
        nullable=True
    )


    name = Column(
        String(255),
        nullable=False
    )


    destination_url = Column(
        Text,
        nullable=False
    )


    tracking_code = Column(
        String(255),
        unique=True,
        index=True,
        nullable=False
    )


    is_active = Column(
        Boolean,
        default=True
    )


    created_at = Column(
        DateTime,
        default=datetime.utcnow
    )


    program = relationship(
        "AffiliateProgram"
    )


    content_asset = relationship(
        "AffiliateContentAsset"
    )
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    ForeignKey,
    DateTime,
)

from datetime import datetime

from app.database.base import Base


class ContentApproval(Base):

    __tablename__ = "content_approvals"


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


    decision = Column(
        String(50),
        nullable=False,
    )


    reason = Column(
        Text,
        nullable=True,
    )


    score = Column(
        Integer,
        nullable=False,
    )


    created_at = Column(
        DateTime,
        default=datetime.utcnow,
    )
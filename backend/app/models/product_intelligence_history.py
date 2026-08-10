"""
Product Intelligence History

Stores historical AI evaluations
for affiliate opportunities.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)

from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class ProductIntelligenceHistory(Base):

    __tablename__ = "product_intelligence_history"


    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )


    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )


    score: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )


    grade: Mapped[str] = mapped_column(
        String(5),
        nullable=False,
    )


    confidence: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )


    recommendation: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
    )


    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
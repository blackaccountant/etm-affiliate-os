"""
Product Intelligence History

Stores meaningful historical AI evaluations
for affiliate opportunities.

A fingerprint identifies the underlying
intelligence snapshot so identical evaluations
are not stored repeatedly.
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

    # =========================================================
    # Identity
    # =========================================================

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    # =========================================================
    # Product
    # =========================================================

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        nullable=False,
        index=True,
    )

    # =========================================================
    # Intelligence
    # =========================================================

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

    # =========================================================
    # Fingerprint
    # =========================================================

    fingerprint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
        default="",
    )

    # =========================================================
    # Recommendation
    # =========================================================

    recommendation: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
    )

    # =========================================================
    # Timestamp
    # =========================================================

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
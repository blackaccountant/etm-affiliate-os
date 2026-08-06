from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class Product(Base):
    """
    Affiliate Intelligence Record

    Represents a researched business opportunity
    stored in ETM AI OS.
    """

    __tablename__ = "products"

    # ----------------------------
    # Identity
    # ----------------------------

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    website: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        unique=True,
        index=True,
    )

    # ----------------------------
    # Business Information
    # ----------------------------

    category: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # ----------------------------
    # Affiliate Information
    # ----------------------------

    affiliate_program: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    affiliate_url: Mapped[str | None] = mapped_column(
        String(1000),
        nullable=True,
    )

    commission_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    commission_value: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    cookie_duration: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # ----------------------------
    # Intelligence
    # ----------------------------

    affiliate_score: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    grade: Mapped[str] = mapped_column(
        String(5),
        default="F",
        nullable=False,
    )

    confidence: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    summary: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
    )

    recommendation: Mapped[str] = mapped_column(
        Text,
        default="",
        nullable=False,
    )

    # ----------------------------
    # Status
    # ----------------------------

    status: Mapped[str] = mapped_column(
        String(100),
        default="active",
        nullable=False,
    )

    # ----------------------------
    # Audit
    # ----------------------------

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
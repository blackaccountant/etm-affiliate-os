"""
Affiliate Conversion Service

Creates and manages affiliate conversions.

Business rules:

    1. One external conversion ID per affiliate program.
    2. One earning per conversion.
    3. Conversion + earning are created atomically.
    4. Duplicate requests return the existing conversion.
    5. Database constraints provide final duplicate protection.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.affiliate_conversion import AffiliateConversion
from app.models.affiliate_earning import AffiliateEarning
from app.models.affiliate_link import AffiliateLink
from app.models.affiliate_program import AffiliateProgram


class AffiliateConversionService:

    def __init__(self, db: Session):
        self.db = db

    # =========================================================
    # CREATE CONVERSION
    # =========================================================

    def create_conversion(
        self,
        affiliate_program_id: int,
        sale_amount: Decimal,
        currency: str = "USD",
        affiliate_link_id: Optional[int] = None,
        tracking_code: Optional[str] = None,
        external_conversion_id: Optional[str] = None,
        customer_reference: Optional[str] = None,
        conversion_status: str = "approved",
        commission_rate: Optional[Decimal] = None,
        source: str = "api",
        metadata_json: Optional[str] = None,
    ):
        """
        Create an affiliate conversion and exactly one earning.

        Idempotency is based on:

            affiliate_program_id
            +
            external_conversion_id

        If that combination already exists, the existing
        conversion is returned and no new earning is created.
        """

        try:

            # =================================================
            # 1. Validate affiliate program
            # =================================================

            program = (
                self.db.query(AffiliateProgram)
                .filter(
                    AffiliateProgram.id
                    == affiliate_program_id
                )
                .first()
            )

            if not program:
                raise ValueError(
                    "Affiliate program not found"
                )

            # =================================================
            # 2. Resolve affiliate link
            # =================================================

            affiliate_link = None

            if affiliate_link_id is not None:

                affiliate_link = (
                    self.db.query(AffiliateLink)
                    .filter(
                        AffiliateLink.id
                        == affiliate_link_id
                    )
                    .first()
                )

                if not affiliate_link:
                    raise ValueError(
                        "Affiliate link not found"
                    )

            elif tracking_code:

                affiliate_link = (
                    self.db.query(AffiliateLink)
                    .filter(
                        AffiliateLink.tracking_code
                        == tracking_code
                    )
                    .first()
                )

                if not affiliate_link:
                    raise ValueError(
                        "Affiliate tracking code not found"
                    )

            # =================================================
            # 3. Normalize external ID
            # =================================================

            if external_conversion_id is not None:

                external_conversion_id = (
                    str(external_conversion_id).strip()
                )

                if not external_conversion_id:
                    external_conversion_id = None

            # =================================================
            # 4. Idempotency lookup
            # =================================================

            if external_conversion_id:

                existing = (
                    self.db.query(AffiliateConversion)
                    .filter(
                        AffiliateConversion
                        .affiliate_program_id
                        == affiliate_program_id,
                        AffiliateConversion
                        .external_conversion_id
                        == external_conversion_id,
                    )
                    .first()
                )

                if existing:

                    return existing

            # =================================================
            # 5. Normalize financial values
            # =================================================

            normalized_sale_amount = Decimal(
                str(sale_amount)
            )

            if normalized_sale_amount < 0:
                raise ValueError(
                    "Sale amount cannot be negative"
                )

            # =================================================
            # 6. Determine commission
            # =================================================

            commission_type = getattr(
                program,
                "commission_type",
                None,
            )

            program_value = getattr(
                program,
                "commission_value",
                None,
            )

            normalized_type = (
                str(commission_type)
                .lower()
                .strip()
                if commission_type
                else ""
            )

            # -------------------------------------------------
            # Explicit commission rate supplied by caller
            # -------------------------------------------------

            if commission_rate is not None:

                commission_rate = Decimal(
                    str(commission_rate)
                )

                if commission_rate < 0:
                    raise ValueError(
                        "Commission rate cannot be negative"
                    )

            # -------------------------------------------------
            # Commission from affiliate program
            # -------------------------------------------------

            elif (
                program_value is not None
                and (
                    "percentage" in normalized_type
                    or "percent" in normalized_type
                    or "%" in normalized_type
                )
            ):

                commission_rate = Decimal(
                    str(program_value)
                )

            # -------------------------------------------------
            # Fixed commission
            # -------------------------------------------------

            elif (
                program_value is not None
                and "fixed" in normalized_type
            ):

                commission_rate = Decimal("0")

            # -------------------------------------------------
            # No commission configured
            # -------------------------------------------------

            else:

                commission_rate = Decimal("0")

            # =================================================
            # 7. Calculate commission
            # =================================================

            if (
                program_value is not None
                and "fixed" in normalized_type
                and commission_rate == Decimal("0")
            ):

                commission_amount = Decimal(
                    str(program_value)
                )

            else:

                commission_amount = (
                    normalized_sale_amount
                    * commission_rate
                    / Decimal("100")
                )

            if commission_amount < 0:
                raise ValueError(
                    "Commission amount cannot be negative"
                )

            # =================================================
            # 8. Create conversion
            # =================================================

            now = datetime.utcnow()

            conversion = AffiliateConversion(
                affiliate_link_id=(
                    affiliate_link.id
                    if affiliate_link
                    else None
                ),
                affiliate_program_id=(
                    affiliate_program_id
                ),
                external_conversion_id=(
                    external_conversion_id
                ),
                customer_reference=(
                    customer_reference
                ),
                sale_amount=(
                    normalized_sale_amount
                ),
                currency=currency.upper(),
                conversion_status=(
                    conversion_status.lower()
                ),
                commission_rate=(
                    commission_rate
                ),
                commission_amount=(
                    commission_amount
                ),
                source=source,
                metadata_json=metadata_json,
                created_at=now,
                updated_at=now,
            )

            self.db.add(conversion)

            # =================================================
            # 9. Flush conversion
            # =================================================

            self.db.flush()

            # =================================================
            # 10. Determine earning status
            # =================================================

            earning_status = (
                "pending"
                if conversion_status.lower()
                == "pending"
                else "approved"
            )

            # =================================================
            # 11. Create exactly ONE earning
            # =================================================

            earning = AffiliateEarning(
                conversion_id=conversion.id,
                affiliate_program_id=(
                    affiliate_program_id
                ),
                gross_amount=(
                    normalized_sale_amount
                ),
                commission_rate=(
                    commission_rate
                ),
                commission_amount=(
                    commission_amount
                ),
                currency=currency.upper(),
                status=earning_status,
                payout_reference=None,
                paid_at=None,
                payout_id=None,
                created_at=now,
                updated_at=now,
            )

            self.db.add(earning)

            # =================================================
            # 12. Atomic commit
            # =================================================

            self.db.commit()

            self.db.refresh(conversion)

            return conversion

        except ValueError:

            self.db.rollback()
            raise

        except IntegrityError:

            # =================================================
            # Database-level idempotency protection
            # =================================================

            self.db.rollback()

            if external_conversion_id:

                existing = (
                    self.db.query(
                        AffiliateConversion
                    )
                    .filter(
                        AffiliateConversion
                        .affiliate_program_id
                        == affiliate_program_id,
                        AffiliateConversion
                        .external_conversion_id
                        == external_conversion_id,
                    )
                    .first()
                )

                if existing:

                    return existing

            raise

        except Exception:

            self.db.rollback()
            raise

    # =========================================================
    # GET SINGLE CONVERSION
    # =========================================================

    def get_conversion(
        self,
        conversion_id: int,
    ):

        return (
            self.db.query(AffiliateConversion)
            .filter(
                AffiliateConversion.id
                == conversion_id
            )
            .first()
        )

    # =========================================================
    # LIST CONVERSIONS
    # =========================================================

    def list_conversions(
        self,
        limit: int = 100,
    ):

        return (
            self.db.query(AffiliateConversion)
            .order_by(
                AffiliateConversion.id.desc()
            )
            .limit(limit)
            .all()
        )
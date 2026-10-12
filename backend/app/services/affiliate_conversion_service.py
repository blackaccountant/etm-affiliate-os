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
from app.attribution.bridge_contracts import AttributionBridgeConflict


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
            conversion, _, created = self._create_conversion_uncommitted(
                affiliate_program_id=affiliate_program_id,
                sale_amount=sale_amount,
                currency=currency,
                affiliate_link_id=affiliate_link_id,
                tracking_code=tracking_code,
                external_conversion_id=external_conversion_id,
                customer_reference=customer_reference,
                conversion_status=conversion_status,
                commission_rate=commission_rate,
                source=source,
                metadata_json=metadata_json,
                strict_replay=False,
            )
            if created:
                self.db.commit()
                self.db.refresh(conversion)
            return conversion
        except ValueError:
            self.db.rollback()
            raise
        except IntegrityError:
            self.db.rollback()
            normalized_external = self._external_id(external_conversion_id)
            if normalized_external:
                existing = self.db.query(AffiliateConversion).filter_by(
                    affiliate_program_id=affiliate_program_id,
                    external_conversion_id=normalized_external,
                ).first()
                if existing:
                    return existing
            raise
        except Exception:
            self.db.rollback()
            raise

    @staticmethod
    def _external_id(value: object | None) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    def _program_and_link(self, affiliate_program_id, affiliate_link_id, tracking_code):
        program = self.db.query(AffiliateProgram).filter_by(id=affiliate_program_id).first()
        if not program:
            raise ValueError("Affiliate program not found")
        link = None
        if affiliate_link_id is not None:
            link = self.db.query(AffiliateLink).filter_by(id=affiliate_link_id).first()
            if not link:
                raise ValueError("Affiliate link not found")
        elif tracking_code:
            link = self.db.query(AffiliateLink).filter_by(tracking_code=tracking_code).first()
            if not link:
                raise ValueError("Affiliate tracking code not found")
        return program, link

    @staticmethod
    def _commercial_values(program, sale_amount, currency, conversion_status, commission_rate, source):
        sale = Decimal(str(sale_amount))
        if sale < 0:
            raise ValueError("Sale amount cannot be negative")
        commission_type = getattr(program, "commission_type", None)
        program_value = getattr(program, "commission_value", None)
        normalized_type = str(commission_type).lower().strip() if commission_type else ""
        if commission_rate is not None:
            rate = Decimal(str(commission_rate))
            if rate < 0:
                raise ValueError("Commission rate cannot be negative")
        elif program_value is not None and any(
            marker in normalized_type for marker in ("percentage", "percent", "%")
        ):
            rate = Decimal(str(program_value))
        else:
            rate = Decimal("0")
        if program_value is not None and "fixed" in normalized_type and rate == 0:
            commission = Decimal(str(program_value))
        else:
            commission = sale * rate / Decimal("100")
        if commission < 0:
            raise ValueError("Commission amount cannot be negative")
        status = conversion_status.lower()
        return {
            "sale_amount": sale,
            "currency": currency.upper(),
            "conversion_status": status,
            "commission_rate": rate,
            "commission_amount": commission,
            "source": source,
            "earning_status": "pending" if status == "pending" else "approved",
        }

    @staticmethod
    def _decimal_equal(left, right, quantum: str) -> bool:
        return Decimal(str(left)).quantize(Decimal(quantum)) == Decimal(str(right)).quantize(Decimal(quantum))

    @staticmethod
    def _provider_values(
        sale_amount,
        currency,
        conversion_status,
        commission_amount,
        source,
    ):
        sale = Decimal(str(sale_amount))
        commission = Decimal(str(commission_amount))
        status = str(conversion_status).strip().lower()
        if status not in {"pending", "approved"}:
            raise ValueError("provider conversion status must be pending or approved")
        normalized_currency = str(currency).strip().upper()
        if not normalized_currency:
            raise ValueError("provider conversion currency is required")
        rate = (
            Decimal("0")
            if sale == 0
            else (commission / sale) * Decimal("100")
        )
        return {
            "sale_amount": sale,
            "currency": normalized_currency,
            "conversion_status": status,
            "commission_rate": rate,
            "commission_amount": commission,
            "source": str(source).strip(),
            "earning_status": "approved" if status == "approved" else "pending",
        }

    def _upsert_provider_conversion_uncommitted(
        self,
        *,
        affiliate_program_id: int,
        sale_amount: Decimal,
        commission_amount: Decimal,
        currency: str,
        affiliate_link_id: int,
        external_conversion_id: str,
        customer_reference: Optional[str],
        conversion_status: str,
        source: str,
        metadata_json: Optional[str],
    ):
        """Upsert one immutable provider financial event without committing.

        Provider correction rows are represented as distinct signed-delta events
        using their own external conversion IDs. The same provider event may
        later promote from pending to approved, but immutable commercial values
        may not change.
        """
        _, link = self._program_and_link(
            affiliate_program_id,
            affiliate_link_id,
            None,
        )
        if link is None:
            raise ValueError("provider conversion requires affiliate_link_id")
        external_id = self._external_id(external_conversion_id)
        if external_id is None:
            raise ValueError("provider conversion requires external_conversion_id")
        values = self._provider_values(
            sale_amount,
            currency,
            conversion_status,
            commission_amount,
            source,
        )
        existing = self.db.query(AffiliateConversion).filter_by(
            affiliate_program_id=affiliate_program_id,
            external_conversion_id=external_id,
        ).first()
        now = datetime.utcnow()
        if existing is not None:
            same = (
                existing.affiliate_link_id == link.id
                and self._decimal_equal(existing.sale_amount, values["sale_amount"], "0.01")
                and existing.currency == values["currency"]
                and self._decimal_equal(existing.commission_rate, values["commission_rate"], "0.0001")
                and self._decimal_equal(existing.commission_amount, values["commission_amount"], "0.01")
                and existing.source == values["source"]
            )
            if not same:
                raise AttributionBridgeConflict(
                    "provider conversion identity conflicts with immutable commercial input"
                )
            earning = self.db.query(AffiliateEarning).filter_by(
                conversion_id=existing.id
            ).one_or_none()
            if earning is None:
                raise AttributionBridgeConflict(
                    "existing provider conversion has no durable earning"
                )
            if (
                existing.conversion_status == "pending"
                and values["conversion_status"] == "approved"
            ):
                existing.conversion_status = "approved"
                earning.status = "approved"
            elif (
                existing.conversion_status == "approved"
                and values["conversion_status"] == "pending"
            ):
                # Provider lifecycle must never regress ETM payout authority.
                pass
            else:
                existing.conversion_status = values["conversion_status"]
                earning.status = values["earning_status"]
            existing.metadata_json = metadata_json
            existing.updated_at = now
            earning.updated_at = now
            return existing, earning, False

        conversion = AffiliateConversion(
            affiliate_link_id=link.id,
            affiliate_program_id=affiliate_program_id,
            external_conversion_id=external_id,
            customer_reference=customer_reference,
            sale_amount=values["sale_amount"],
            currency=values["currency"],
            conversion_status=values["conversion_status"],
            commission_rate=values["commission_rate"],
            commission_amount=values["commission_amount"],
            source=values["source"],
            metadata_json=metadata_json,
            created_at=now,
            updated_at=now,
        )
        self.db.add(conversion)
        self.db.flush()
        earning = AffiliateEarning(
            conversion_id=conversion.id,
            affiliate_program_id=affiliate_program_id,
            gross_amount=values["sale_amount"],
            commission_rate=values["commission_rate"],
            commission_amount=values["commission_amount"],
            currency=values["currency"],
            status=values["earning_status"],
            payout_reference=None,
            paid_at=None,
            payout_id=None,
            created_at=now,
            updated_at=now,
        )
        self.db.add(earning)
        self.db.flush()
        return conversion, earning, True

    def _assert_strict_replay(self, existing, link, values):
        same = (
            existing.affiliate_link_id == (link.id if link else None)
            and self._decimal_equal(existing.sale_amount, values["sale_amount"], "0.01")
            and existing.currency == values["currency"]
            and existing.conversion_status == values["conversion_status"]
            and self._decimal_equal(existing.commission_rate, values["commission_rate"], "0.0001")
            and self._decimal_equal(existing.commission_amount, values["commission_amount"], "0.01")
            and existing.source == values["source"]
        )
        if not same:
            raise AttributionBridgeConflict(
                "conversion source identity conflicts with immutable commercial input"
            )

    def _create_conversion_uncommitted(
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
        *,
        strict_replay: bool = False,
    ):
        """Create conversion and earning without committing or rolling back."""
        program, link = self._program_and_link(
            affiliate_program_id, affiliate_link_id, tracking_code,
        )
        external_id = self._external_id(external_conversion_id)
        existing = None
        if external_id:
            existing = self.db.query(AffiliateConversion).filter_by(
                affiliate_program_id=affiliate_program_id,
                external_conversion_id=external_id,
            ).first()
        values = None
        if existing is not None and not strict_replay:
            earning = self.db.query(AffiliateEarning).filter_by(conversion_id=existing.id).one_or_none()
            return existing, earning, False
        values = self._commercial_values(
            program, sale_amount, currency, conversion_status, commission_rate, source,
        )
        if existing is not None:
            self._assert_strict_replay(existing, link, values)
            earning = self.db.query(AffiliateEarning).filter_by(conversion_id=existing.id).one_or_none()
            if earning is None:
                raise AttributionBridgeConflict("existing conversion has no durable earning")
            return existing, earning, False

        now = datetime.utcnow()
        conversion = AffiliateConversion(
            affiliate_link_id=link.id if link else None,
            affiliate_program_id=affiliate_program_id,
            external_conversion_id=external_id,
            customer_reference=customer_reference,
            sale_amount=values["sale_amount"],
            currency=values["currency"],
            conversion_status=values["conversion_status"],
            commission_rate=values["commission_rate"],
            commission_amount=values["commission_amount"],
            source=values["source"],
            metadata_json=metadata_json,
            created_at=now,
            updated_at=now,
        )
        self.db.add(conversion)
        self.db.flush()
        earning = AffiliateEarning(
            conversion_id=conversion.id,
            affiliate_program_id=affiliate_program_id,
            gross_amount=values["sale_amount"],
            commission_rate=values["commission_rate"],
            commission_amount=values["commission_amount"],
            currency=values["currency"],
            status=values["earning_status"],
            payout_reference=None,
            paid_at=None,
            payout_id=None,
            created_at=now,
            updated_at=now,
        )
        self.db.add(earning)
        self.db.flush()
        return conversion, earning, True

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

"""Read-only, non-accounting projection contracts for M10A6 settled commission."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


ProjectionDimension = Literal[
    "affiliate_program", "product", "content_asset", "attribution_publication",
    "publishing_authority", "distribution_run", "affiliate_link", "attribution_context",
    "attribution_click", "conversion", "earning", "settlement_link",
]

ALLOWED_DIMENSIONS = frozenset({
    "affiliate_program", "product", "content_asset", "attribution_publication",
    "publishing_authority", "distribution_run", "affiliate_link", "attribution_context",
    "attribution_click", "conversion", "earning", "settlement_link",
})
PROJECTION_SEMANTICS = "settled commission projection from currently authoritative records"


def normalize_dimensions(dimensions: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    values = tuple(dimensions or ())
    if len(set(values)) != len(values):
        raise ValueError("projection dimensions must be unique")
    unknown = set(values) - ALLOWED_DIMENSIONS
    if unknown:
        raise ValueError(f"unsupported projection dimensions: {', '.join(sorted(unknown))}")
    return tuple(sorted(values))


def normalize_currency(currency: str | None) -> str | None:
    if currency is None:
        return None
    if not isinstance(currency, str) or len(currency.strip()) != 3 or not currency.strip().isalpha():
        raise ValueError("currency must be a three-letter code")
    return currency.strip().upper()


@dataclass(frozen=True)
class RealizedRevenueProjectionRequest:
    dimensions: tuple[str, ...] = ()
    currency: str | None = None

    def normalized(self) -> "RealizedRevenueProjectionRequest":
        return RealizedRevenueProjectionRequest(
            dimensions=normalize_dimensions(self.dimensions), currency=normalize_currency(self.currency),
        )


@dataclass(frozen=True)
class SettledCommissionProjectionRow:
    """One currency-scoped, non-accounting settled-commission projection bucket."""

    currency: str
    commission_amount: Decimal
    dimensions: tuple[tuple[str, str | int | None], ...]
    semantics: str = PROJECTION_SEMANTICS

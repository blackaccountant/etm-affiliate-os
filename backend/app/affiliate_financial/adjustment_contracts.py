"""Bounded, privacy-safe contracts for immutable affiliate financial adjustments."""
from decimal import Decimal
import re
from app.attribution.contracts import AttributionIdempotencyConflict, canonical_fingerprint

ADJUSTMENT_TYPES = frozenset({"REFUND", "REVERSAL", "CHARGEBACK", "CLAWBACK", "CANCELLATION", "CORRECTION", "RESTORATION"})
REDUCTIONS = frozenset({"REFUND", "REVERSAL", "CHARGEBACK", "CLAWBACK", "CANCELLATION"})
INCREASES = frozenset({"CORRECTION", "RESTORATION"})
SOURCE_NAMESPACE = "m10a7.adjustment"

class AffiliateFinancialAdjustmentConflict(AttributionIdempotencyConflict): pass

def adjustment_fingerprint(*, earning_id:int, program_id:int, adjustment_type:str, adjustment_amount:Decimal, currency:str, source_namespace:str, source_event_digest:str) -> str:
    if adjustment_type not in ADJUSTMENT_TYPES: raise ValueError("unsupported adjustment type")
    amount=Decimal(str(adjustment_amount))
    if not amount: raise ValueError("adjustment amount must be nonzero")
    if adjustment_type in REDUCTIONS and amount >= 0: raise ValueError("reduction adjustment must be negative")
    if adjustment_type in INCREASES and amount <= 0: raise ValueError("restoration adjustment must be positive")
    if not isinstance(currency,str) or len(currency.strip()) != 3: raise ValueError("currency must be three letters")
    if not isinstance(source_namespace,str) or not re.fullmatch(r"[a-z][a-z0-9.-]{0,62}",source_namespace): raise ValueError("source namespace is invalid")
    if not isinstance(source_event_digest,str) or len(source_event_digest) != 64: raise ValueError("source event digest must be SHA-256")
    return canonical_fingerprint("m10a7-adjustment-v1", {"earning_id":earning_id,"program_id":program_id,"type":adjustment_type,"amount":str(amount),"currency":currency.upper(),"namespace":source_namespace,"digest":source_event_digest})

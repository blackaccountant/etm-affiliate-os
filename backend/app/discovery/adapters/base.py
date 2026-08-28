"""Source-agnostic discovery adapter contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from app.discovery.contracts import DiscoveryCandidateCreate


@dataclass(frozen=True)
class DiscoveryEvidence:
    claim_type: str
    observed_value: Any
    source_url: str
    excerpt: str
    http_status: int | None
    content_hash: str
    confidence: int


@dataclass(frozen=True)
class AdapterDiscoveryResult:
    candidate: DiscoveryCandidateCreate
    evidence: tuple[DiscoveryEvidence, ...]


@runtime_checkable
class DiscoveryAdapter(Protocol):
    """Contract shared by official-site and future provider adapters."""

    name: str
    source_type: str

    def discover(self, source: str) -> AdapterDiscoveryResult | None: ...

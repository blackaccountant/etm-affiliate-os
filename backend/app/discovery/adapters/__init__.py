"""Discovery source adapters."""

from app.discovery.adapters.base import AdapterDiscoveryResult, DiscoveryAdapter, DiscoveryEvidence
from app.discovery.adapters.official_site import OfficialSiteDiscoveryAdapter

__all__ = ["AdapterDiscoveryResult", "DiscoveryAdapter", "DiscoveryEvidence", "OfficialSiteDiscoveryAdapter"]

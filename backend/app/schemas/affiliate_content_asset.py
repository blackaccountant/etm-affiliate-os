"""
Affiliate Content Asset Schema

Defines AI-generated marketing assets.
"""


from typing import Any, List

from pydantic import BaseModel



class AffiliateContentAssetSchema(BaseModel):

    asset_type: str

    title: str

    target_keyword: str | None = None

    audience: Any = None

    search_intent: str | None = None

    content_outline: List[str] = []

    call_to_action: str | None = None
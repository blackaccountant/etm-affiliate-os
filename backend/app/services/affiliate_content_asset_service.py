"""
Affiliate Content Asset Service

Handles saving generated content assets.

Production behavior:

- Prevents duplicate assets when the content strategy is unchanged.
- Creates a new version only when the strategy changes.
- Tracks the active version.
- Preserves historical versions.
"""

from __future__ import annotations

import ast
from typing import Any

from sqlalchemy.orm import Session

from app.models.affiliate_content_asset import (
    AffiliateContentAsset,
)

from app.schemas.affiliate_content_asset import (
    AffiliateContentAssetSchema,
)


class AffiliateContentAssetService:

    def __init__(
        self,
        db: Session,
    ):
        self.db = db

    # =========================================================
    # NORMALIZATION
    # =========================================================

    @staticmethod
    def _normalize(value: Any) -> str:
        """
        Convert strategy values into a deterministic string.

        Handles:
        - None
        - strings
        - lists
        - tuples
        - sets
        - database strings representing Python lists
        """

        if value is None:
            return ""

        # -----------------------------------------------------
        # Already a collection
        # -----------------------------------------------------

        if isinstance(value, (list, tuple, set)):
            return "|".join(
                str(item).strip()
                for item in value
            )

        # -----------------------------------------------------
        # Database may contain serialized list strings
        # Example:
        #
        # "['business owners', 'software buyers']"
        # -----------------------------------------------------

        if isinstance(value, str):

            value = value.strip()

            if not value:
                return ""

            if (
                value.startswith("[")
                and value.endswith("]")
            ):

                try:

                    parsed = ast.literal_eval(
                        value
                    )

                    if isinstance(
                        parsed,
                        (list, tuple, set),
                    ):

                        return "|".join(
                            str(item).strip()
                            for item in parsed
                        )

                except (
                    ValueError,
                    SyntaxError,
                ):
                    pass

            return value

        # -----------------------------------------------------
        # Everything else
        # -----------------------------------------------------

        return str(value).strip()

    # =========================================================
    # STRATEGY IDENTITY
    # =========================================================

    def _strategy_matches(
        self,
        existing: AffiliateContentAsset,
        incoming: AffiliateContentAssetSchema,
    ) -> bool:
        """
        Determine whether an existing asset represents
        the same content strategy as the incoming asset.

        generated_content is deliberately excluded because
        content generation happens after the asset exists.
        """

        fields = (
            "asset_type",
            "title",
            "target_keyword",
            "audience",
            "search_intent",
            "content_outline",
            "call_to_action",
        )

        for field in fields:

            existing_value = self._normalize(
                getattr(
                    existing,
                    field,
                    None,
                )
            )

            incoming_value = self._normalize(
                getattr(
                    incoming,
                    field,
                    None,
                )
            )

            if existing_value != incoming_value:

                return False

        return True

    # =========================================================
    # FIND LATEST VERSION
    # =========================================================

    def _get_latest_version(
        self,
        product_id: int,
        title: str,
    ):

        return (
            self.db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.product_id
                == product_id,
                AffiliateContentAsset.title
                == title,
            )
            .order_by(
                AffiliateContentAsset.version.desc()
            )
            .first()
        )

    # =========================================================
    # FIND ACTIVE VERSION
    # =========================================================

    def _get_active_asset(
        self,
        product_id: int,
        title: str,
    ):

        return (
            self.db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.product_id
                == product_id,
                AffiliateContentAsset.title
                == title,
                AffiliateContentAsset.is_active
                == True,
            )
            .order_by(
                AffiliateContentAsset.version.desc()
            )
            .first()
        )

    # =========================================================
    # ARCHIVE ACTIVE VERSION
    # =========================================================

    def _archive_previous_version(
        self,
        product_id: int,
        title: str,
    ):

        active_assets = (
            self.db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.product_id
                == product_id,
                AffiliateContentAsset.title
                == title,
                AffiliateContentAsset.is_active
                == True,
            )
            .all()
        )

        for asset in active_assets:

            asset.is_active = False

    # =========================================================
    # SAVE ASSETS
    # =========================================================

    def save_assets(
        self,
        product_id: int,
        assets: list[
            AffiliateContentAssetSchema
        ],
    ):
        """
        Save content strategies idempotently.

        Same strategy:
            return existing active asset.

        Changed strategy:
            create next version.
        """

        saved = []

        for asset in assets:

            # -------------------------------------------------
            # Check current active asset
            # -------------------------------------------------

            active = self._get_active_asset(
                product_id,
                asset.title,
            )

            if active:

                if self._strategy_matches(
                    active,
                    asset,
                ):

                    # -----------------------------------------
                    # EXACT SAME STRATEGY
                    # -----------------------------------------

                    saved.append(
                        active
                    )

                    continue

            # -------------------------------------------------
            # Find latest historical version
            # -------------------------------------------------

            latest = self._get_latest_version(
                product_id,
                asset.title,
            )

            if latest:

                next_version = (
                    latest.version + 1
                )

                parent_id = latest.id

            else:

                next_version = 1

                parent_id = None

            # -------------------------------------------------
            # Archive previous active version
            # -------------------------------------------------

            self._archive_previous_version(
                product_id,
                asset.title,
            )

            # -------------------------------------------------
            # Create new version
            # -------------------------------------------------

            record = AffiliateContentAsset(

                product_id=product_id,

                parent_id=parent_id,

                version=next_version,

                is_active=True,

                asset_type=(
                    asset.asset_type
                ),

                title=(
                    asset.title
                ),

                target_keyword=(
                    asset.target_keyword
                ),

                audience=(
                    str(asset.audience)
                ),

                search_intent=(
                    asset.search_intent
                ),

                content_outline=(
                    str(
                        asset.content_outline
                    )
                ),

                call_to_action=(
                    asset.call_to_action
                ),

                status="generated",
            )

            self.db.add(
                record
            )

            self.db.flush()

            saved.append(
                record
            )

        # -----------------------------------------------------
        # Commit
        # -----------------------------------------------------

        self.db.commit()

        # -----------------------------------------------------
        # Refresh
        # -----------------------------------------------------

        for item in saved:

            self.db.refresh(
                item
            )

        return saved
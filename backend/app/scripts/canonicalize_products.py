"""
ETM Affiliate OS
Product Canonicalization Migration

Canonicalizes product website URLs while safely merging products
that collide after canonicalization.
"""

from __future__ import annotations

from collections import defaultdict

from app.database.session import SessionLocal
from app.models.product import Product
from app.models.product_intelligence_history import ProductIntelligenceHistory
from app.services.url_normalizer import normalize_url


def canonicalize_products() -> dict:
    db = SessionLocal()

    try:
        products = (
            db.query(Product)
            .order_by(Product.id.asc())
            .all()
        )

        if not products:
            return {
                "success": True,
                "products_processed": 0,
                "duplicates_merged": 0,
                "history_reassigned": 0,
                "message": "No products found.",
            }

        groups: dict[str, list[Product]] = defaultdict(list)

        # ---------------------------------------------------------
        # Build canonical URL groups
        # ---------------------------------------------------------

        for product in products:
            canonical_url = normalize_url(product.website)
            groups[canonical_url].append(product)

        duplicates_merged = 0
        history_reassigned = 0

        # ---------------------------------------------------------
        # Process each canonical URL group
        # ---------------------------------------------------------

        for canonical_url, group in groups.items():

            # No duplicate.
            if len(group) == 1:
                product = group[0]
                product.website = canonical_url
                continue

            # -----------------------------------------------------
            # Duplicate group
            #
            # Lowest ID becomes the survivor.
            # -----------------------------------------------------

            group.sort(key=lambda product: product.id)

            survivor = group[0]
            duplicates = group[1:]

            # -----------------------------------------------------
            # Move intelligence history from duplicates
            # to the survivor.
            # -----------------------------------------------------

            for duplicate in duplicates:

                history_rows = (
                    db.query(ProductIntelligenceHistory)
                    .filter(
                        ProductIntelligenceHistory.product_id
                        == duplicate.id
                    )
                    .all()
                )

                for history in history_rows:
                    history.product_id = survivor.id
                    history_reassigned += 1

                # -------------------------------------------------
                # Delete duplicate product BEFORE changing the
                # survivor URL.
                #
                # This is required because products.website has
                # a UNIQUE constraint.
                # -------------------------------------------------

                db.delete(duplicate)
                duplicates_merged += 1

            # -----------------------------------------------------
            # Flush the deletes first.
            #
            # PostgreSQL must see the duplicate URL removed before
            # the survivor receives the canonical URL.
            # -----------------------------------------------------

            db.flush()

            # -----------------------------------------------------
            # Now safely canonicalize the survivor.
            # -----------------------------------------------------

            survivor.website = canonical_url

        # ---------------------------------------------------------
        # Final flush + commit
        # ---------------------------------------------------------

        db.flush()
        db.commit()

        return {
            "success": True,
            "products_processed": len(products),
            "duplicates_merged": duplicates_merged,
            "history_reassigned": history_reassigned,
            "message": "Product canonicalization completed successfully.",
        }

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


__all__ = [
    "canonicalize_products",
]

"""
Affiliate Content Asset Service

Handles saving generated content assets.

Production features:
- Duplicate prevention
- Content versioning
- Active version tracking
- Historical version preservation
"""


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



    def _get_latest_version(
        self,
        product_id: int,
        title: str,
    ):
        """
        Find latest content version for a product.
        """

        return (
            self.db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.product_id == product_id,
                AffiliateContentAsset.title == title,
            )
            .order_by(
                AffiliateContentAsset.version.desc()
            )
            .first()
        )



    def _archive_previous_version(
        self,
        product_id: int,
        title: str,
    ):
        """
        Mark current active version as inactive.
        """

        active_assets = (
            self.db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.product_id == product_id,
                AffiliateContentAsset.title == title,
                AffiliateContentAsset.is_active == True,
            )
            .all()
        )


        for asset in active_assets:

            asset.is_active = False



    def save_assets(
        self,
        product_id: int,
        assets: list[AffiliateContentAssetSchema],
    ):

        saved = []


        for asset in assets:


            latest = self._get_latest_version(
                product_id,
                asset.title,
            )


            # -----------------------------------
            # Determine version
            # -----------------------------------

            if latest:

                next_version = (
                    latest.version + 1
                )

                parent_id = latest.id

            else:

                next_version = 1

                parent_id = None



            # -----------------------------------
            # Archive previous active version
            # -----------------------------------

            self._archive_previous_version(
                product_id,
                asset.title,
            )



            # -----------------------------------
            # Create new version
            # -----------------------------------

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
                    str(
                        asset.audience
                    )
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


            saved.append(
                record
            )


        self.db.commit()



        for item in saved:

            self.db.refresh(
                item
            )



        return saved
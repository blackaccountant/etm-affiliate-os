"""
SEO Optimizer Service

Analyzes affiliate content assets and generates
SEO quality scores.
"""


from sqlalchemy.orm import Session

from app.models.content_seo_score import ContentSEOScore
from app.models.affiliate_content_asset import AffiliateContentAsset



class SEOOptimizerService:


    def __init__(self, db: Session):
        self.db = db



    def analyze_content(
        self,
        content_asset_id: int,
    ):

        asset = (
            self.db.query(
                AffiliateContentAsset
            )
            .filter(
                AffiliateContentAsset.id == content_asset_id
            )
            .first()
        )


        if not asset:
            raise ValueError(
                "Content asset not found"
            )


        keyword_score = self._keyword_score(asset)

        intent_score = self._intent_score(asset)

        readability_score = self._readability_score(asset)

        depth_score = self._depth_score(asset)

        affiliate_fit_score = self._affiliate_fit_score(asset)


        overall = int(
            (
                keyword_score
                + intent_score
                + readability_score
                + depth_score
                + affiliate_fit_score
            )
            / 5
        )


        recommendations = self._recommendations(
            overall
        )


        seo_score = ContentSEOScore(

            content_asset_id=asset.id,

            keyword_score=keyword_score,

            search_intent_score=intent_score,

            readability_score=readability_score,

            content_depth_score=depth_score,

            affiliate_fit_score=affiliate_fit_score,

            overall_score=overall,

            recommendations=recommendations,
        )


        self.db.add(seo_score)


        self.db.commit()

        self.db.refresh(seo_score)


        return seo_score



    def _keyword_score(self, asset):

        if asset.target_keyword:
            return 85

        return 40



    def _intent_score(self, asset):

        if asset.search_intent:
            return 90

        return 50



    def _readability_score(self, asset):

        content = asset.generated_content or ""

        if len(content) > 1000:
            return 85

        if len(content) > 500:
            return 70

        return 50



    def _depth_score(self, asset):

        if asset.content_outline:
            return 80

        return 40



    def _affiliate_fit_score(self, asset):

        if asset.call_to_action:
            return 90

        return 50



    def _recommendations(
        self,
        score
    ):

        if score >= 80:

            return (
                "Content is ready for SEO review "
                "and publishing pipeline."
            )


        return (
            "Improve keyword coverage, "
            "content depth, and conversion elements."
        )
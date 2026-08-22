"""
Product Intelligence Service

Persists affiliate product intelligence,
affiliate programs,
and meaningful historical intelligence snapshots.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.intelligence_fingerprint import (
    create_intelligence_fingerprint,
)

from app.intelligence.models import IntelligenceResult

from app.repositories.product_repository import (
    ProductRepository,
)

from app.schemas.affiliate_analysis import (
    AffiliateAnalysis,
)

from app.workflows.core.workflow_result import (
    DatabaseResult,
)

from app.models.product_intelligence_history import (
    ProductIntelligenceHistory,
)

from app.models.affiliate_program import (
    AffiliateProgram,
)

from app.services.url_normalizer import (
    normalize_url,
)


class ProductIntelligenceService:

    def __init__(
        self,
        db: Session,
    ):

        self.db = db

        self.repository = ProductRepository(
            db
        )


    def save_affiliate_program(
        self,
        product_id: int,
        discovery: dict,
    ):
        """
        Save discovered affiliate program.
        """

        if not discovery:
            return


        if not discovery.get(
            "affiliate_program_found"
        ):
            return


        network = discovery.get(
            "affiliate_platform"
        )

        program_url = discovery.get(
            "program_url"
        )


        existing = (
            self.db.query(
                AffiliateProgram
            )
            .filter(
                AffiliateProgram.product_id == product_id,

                AffiliateProgram.network == network,



            )
            .first()
        )


        evidence = discovery.get(
            "evidence",
            []
        )


        if isinstance(
            evidence,
            list
        ):
            evidence = "\n".join(
                str(item)
                for item in evidence
            )


        if existing:

            existing.commission_type = (
                discovery.get(
                    "commission_type"
                )
            )

            existing.commission_value = (
                discovery.get(
                    "commission_estimate"
                )
            )

            existing.cookie_duration = (
                discovery.get(
                    "cookie_window"
                )
            )

            existing.confidence = (
                discovery.get(
                    "confidence",
                    0,
                )
            )

            existing.evidence = evidence

            return existing



        program = AffiliateProgram(

            product_id=product_id,

            program_name=(
                "Affiliate Program"
            ),

            network=network,

            program_url=program_url,

            commission_type=(
                discovery.get(
                    "commission_type"
                )
            ),

            commission_value=(
                discovery.get(
                    "commission_estimate"
                )
            ),

            cookie_duration=(
                discovery.get(
                    "cookie_window"
                )
            ),

            confidence=(
                discovery.get(
                    "confidence",
                    0,
                )
            ),

            evidence=evidence,

            status="active",

        )


        self.db.add(
            program
        )


        return program



    def save_analysis(
        self,
        analysis: AffiliateAnalysis,
        discovery: dict,
        intelligence: IntelligenceResult,
    ) -> DatabaseResult:
        """
        Save or refresh product intelligence.
        """


        normalized_website = normalize_url(
            analysis.website
        )

        analysis.website = normalized_website


        existing = self.repository.get_by_website(
            normalized_website
        )


        if existing:

            previous_score = (
                existing.affiliate_score
            )


            fingerprint = (
                create_intelligence_fingerprint(
                    score=intelligence.score,
                    grade=intelligence.grade,
                    confidence=intelligence.confidence,
                )
            )


            latest_history = (
                self.db.query(
                    ProductIntelligenceHistory
                )
                .filter(
                    ProductIntelligenceHistory.product_id
                    == existing.id
                )
                .order_by(
                    ProductIntelligenceHistory.created_at.desc(),
                    ProductIntelligenceHistory.id.desc(),
                )
                .first()
            )


            intelligence_changed = True


            if latest_history:

                if (
                    latest_history.fingerprint
                    == fingerprint
                ):
                    intelligence_changed = False



            existing.website = normalized_website

            existing.affiliate_score = int(
                intelligence.score
            )

            existing.grade = (
                intelligence.grade
            )

            existing.confidence = int(
                intelligence.confidence
            )

            existing.summary = (
                intelligence.summary
            )

            existing.recommendation = (
                intelligence.recommendation
            )


            self.save_affiliate_program(
                existing.id,
                discovery,
            )


            if intelligence_changed:

                history = ProductIntelligenceHistory(
                    product_id=existing.id,
                    score=intelligence.score,
                    grade=intelligence.grade,
                    confidence=intelligence.confidence,
                    fingerprint=fingerprint,
                    recommendation=intelligence.recommendation,
                )

                self.db.add(
                    history
                )

                message = (
                    "Product intelligence changed; "
                    "new historical snapshot recorded."
                )

            else:

                message = (
                    "Product intelligence unchanged; "
                    "duplicate history snapshot skipped."
                )


            self.db.commit()


            self.db.refresh(
                existing
            )


            return DatabaseResult(

                saved=False,

                duplicate=True,

                updated=True,

                product_id=existing.id,

                previous_score=previous_score,

                new_score=existing.affiliate_score,

                message=message,

            )



        product = self.repository.create_from_analysis(
            analysis,
            intelligence,
        )


        self.save_affiliate_program(
            product.id,
            discovery,
        )


        fingerprint = (
            create_intelligence_fingerprint(
                score=intelligence.score,
                grade=intelligence.grade,
                confidence=intelligence.confidence,
            )
        )


        history = ProductIntelligenceHistory(
            product_id=product.id,
            score=intelligence.score,
            grade=intelligence.grade,
            confidence=intelligence.confidence,
            fingerprint=fingerprint,
            recommendation=intelligence.recommendation,
        )


        self.db.add(
            history
        )


        self.db.commit()


        return DatabaseResult(

            saved=True,

            duplicate=False,

            updated=False,

            product_id=product.id,

            message=(
                "Product saved successfully "
                "with affiliate program and "
                "intelligence history."
            ),

        )

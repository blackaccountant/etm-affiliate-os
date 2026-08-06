from app.intelligence.scoring import AffiliateScoringEngine
from app.schemas.affiliate_analysis import AffiliateAnalysis


def test_scoring_engine_returns_score():

    engine = AffiliateScoringEngine()

    analysis = AffiliateAnalysis(
        company="Test Company",
        website="https://example.com",
        category="AI SaaS",
        summary="Test summary",
        target_audience=["Developers"],
        pricing_model="Subscription",
        affiliate_program_likely="Yes",
        commission_type="Revenue Share",
        commission_estimate="20%",
        affiliate_score=80,
        recommendation="Promote",
    )

    result = engine.score(analysis)

    assert result is not None
    assert 0 <= result.score <= 100
    assert result.grade is not None
    assert result.confidence >= 0
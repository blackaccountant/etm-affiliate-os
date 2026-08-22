"""
Tests for Intelligence History Service.
"""

from types import SimpleNamespace

from app.services.intelligence_history_service import (
    IntelligenceHistoryService,
)


class FakeRepository:

    def __init__(self, history):

        self.history = history

    def get_by_product_id(
        self,
        product_id,
    ):

        return self.history


# ==========================================================
# History
# ==========================================================

def test_get_history():

    history = [

        SimpleNamespace(
            score=70,
            grade="C",
            confidence=100,
        ),

    ]

    repository = FakeRepository(
        history
    )

    service = IntelligenceHistoryService(
        repository
    )

    result = service.get_history(
        product_id=1
    )

    assert len(result) == 1

    assert result[0].score == 70


# ==========================================================
# Summary
# ==========================================================

def test_get_summary():

    history = [

        SimpleNamespace(
            score=70,
            grade="C",
            confidence=100,
        ),

        SimpleNamespace(
            score=80,
            grade="B",
            confidence=100,
        ),

        SimpleNamespace(
            score=90,
            grade="A",
            confidence=100,
        ),

    ]

    repository = FakeRepository(
        history
    )

    service = IntelligenceHistoryService(
        repository
    )

    result = service.get_summary(
        product_id=1
    )

    assert result["product_id"] == 1

    assert result["evaluations"] == 3

    assert result["latest_score"] == 70

    assert result["average_score"] == 80

    assert result["highest_score"] == 90

    assert result["lowest_score"] == 70

    assert result["trend"] == "DECLINING"

    assert result["score_change"] == -10


# ==========================================================
# Empty History
# ==========================================================

def test_get_summary_without_history():

    repository = FakeRepository(
        []
    )

    service = IntelligenceHistoryService(
        repository
    )

    result = service.get_summary(
        product_id=999
    )

    assert result["product_id"] == 999

    assert result["evaluations"] == 0

    assert result["latest_score"] is None

    assert result["average_score"] == 0

    assert result["highest_score"] is None

    assert result["lowest_score"] is None

    assert result["trend"] == "NO_DATA"


# ==========================================================
# Stable Trend
# ==========================================================

def test_get_summary_stable_trend():

    history = [

        SimpleNamespace(
            score=70,
            grade="C",
            confidence=100,
        ),

        SimpleNamespace(
            score=65,
            grade="C",
            confidence=100,
        ),

    ]

    repository = FakeRepository(
        history
    )

    service = IntelligenceHistoryService(
        repository
    )

    result = service.get_summary(
        product_id=1
    )

    assert result["latest_score"] == 70

    assert result["score_change"] == 5

    assert result["trend"] == "STABLE"
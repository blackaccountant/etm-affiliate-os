from app.models.product import Product


def test_product_model_exists():

    product = Product(
        name="Test AI Tool",
        website="https://example.com",
        category="AI",
        affiliate_program="Unknown",
        commission_type="Revenue Share",
        commission_value="10%",
        affiliate_score=80,
        grade="B",
        confidence=90,
        summary="Test summary",
        recommendation="Test recommendation",
        status="active",
    )

    assert product.name == "Test AI Tool"
    assert product.affiliate_score == 80
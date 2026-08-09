from app.models.product import Product
from app.repositories.product_repository import ProductRepository


def test_product_repository_crud(db_session):

    repository = ProductRepository(
        db_session
    )

    product = Product(
        name="CRUD Test Product",
        website="https://crud-test.example",
        category="AI SaaS",
        affiliate_program="Test Program",
        affiliate_url=None,
        commission_type="Revenue Share",
        commission_value="20%",
        cookie_duration=None,
        affiliate_score=85,
        grade="A",
        confidence=90,
        summary="CRUD test product.",
        recommendation="Good opportunity.",
        status="active",
    )

    # CREATE
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)

    assert product.id is not None

    # GET BY ID
    found = repository.get_by_id(
        product.id
    )

    assert found is not None
    assert found.name == (
        "CRUD Test Product"
    )

    # GET BY WEBSITE
    found_by_website = (
        repository.get_by_website(
            "https://crud-test.example"
        )
    )

    assert found_by_website is not None
    assert found_by_website.id == (
        product.id
    )

    # GET ALL
    products = repository.get_all()

    assert len(products) >= 1

    # UPDATE
    from app.schemas.product import ProductUpdate

    updated = repository.update(
        product,
        ProductUpdate(
            name="Updated CRUD Product"
        ),
    )

    assert updated.name == (
        "Updated CRUD Product"
    )

    # DELETE
    repository.delete(
        updated
    )

    deleted = repository.get_by_id(
        product.id
    )

    assert deleted is None
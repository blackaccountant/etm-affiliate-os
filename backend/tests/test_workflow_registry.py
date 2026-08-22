from app.registry.default_workflows import (
    create_workflow_registry,
)


def test_workflow_registry_exists():

    registry = create_workflow_registry()

    assert registry is not None


def test_affiliate_workflow_registered():

    registry = create_workflow_registry()

    workflow = registry.get(
        "affiliate_discovery"
    )

    assert workflow is not None


def test_product_discovery_workflow_registered():

    registry = create_workflow_registry()

    workflow = registry.get(
        "product_discovery"
    )

    assert workflow is not None


def test_unknown_workflow_returns_none():

    registry = create_workflow_registry()

    workflow = registry.get(
        "unknown"
    )

    assert workflow is None
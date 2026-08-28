from fastapi.testclient import TestClient

from app.main import app
from app.models.execution import Execution
from app.models.mission_record import MissionRecord


client = TestClient(app)


def test_run_affiliate_command(isolated_system_mission_manager, db_session_factory):

    response = client.post(
        "/system/command/run-affiliate"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True

    assert (
        "executed"
        in data["message"].lower()
    )

    session = db_session_factory()
    try:
        assert session.query(MissionRecord).count() == 1
        assert session.query(Execution).count() == 1
    finally:
        session.close()


def test_run_product_discovery_command(isolated_system_mission_manager):

    response = client.post(
        "/system/command/run-product-discovery"
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True

    assert (
        "product discovery"
        in data["message"].lower()
    )


def test_product_discovery_result_reaches_dashboard(isolated_system_mission_manager):

    command_response = client.post(
        "/system/command/run-product-discovery"
    )

    assert command_response.status_code == 200

    dashboard_response = client.get(
        "/system/dashboard"
    )

    assert dashboard_response.status_code == 200

    dashboard = dashboard_response.json()

    mission_result = (
        dashboard["latest_mission_result"]
    )

    assert mission_result is not None

    assert (
        mission_result["workflow"]
        ==
        "product_discovery"
    )

    assert (
        mission_result["success"]
        is True
    )

    products = (
        mission_result["data"]["data"]["products"]
    )

    assert len(products) > 0

    assert "name" in products[0]

    assert "opportunity_score" in products[0]

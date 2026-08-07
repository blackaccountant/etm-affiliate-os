from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_run_workflow():

    response = client.post(
        "/system/run",
        json={
            "workflow": "affiliate_discovery",
            "payload": {
                "url": "https://openrouter.ai"
            },
        },
    )

    assert response.status_code == 200

    data = response.json()

    assert data["success"] is True
    assert data["status"] == "scheduled"
    assert (
        data["workflow"]
        ==
        "affiliate_discovery"
    )
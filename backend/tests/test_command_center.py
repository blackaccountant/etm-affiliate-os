from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_run_affiliate_command():

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
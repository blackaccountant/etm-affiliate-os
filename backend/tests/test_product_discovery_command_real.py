from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_product_discovery_command_executes_real_path():

    response = client.post(
        "/system/run",
        json={
            "workflow": "product_discovery",
            "payload": {
                "url": "https://example.com"
            },
        },
    )


    assert response.status_code == 200


    data = response.json()


    assert data["success"] is True

    assert (
        data["workflow"]
        ==
        "product_discovery"
    )
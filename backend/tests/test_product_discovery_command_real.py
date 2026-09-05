from fastapi.testclient import TestClient

from app.main import app


def test_product_discovery_command_executes_real_path(api_auth_headers):

    client = TestClient(app)

    response = client.post(
        "/system/run",
        headers=api_auth_headers["service"],
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

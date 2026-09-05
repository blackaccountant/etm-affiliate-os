from fastapi.testclient import TestClient

from app.main import app

def test_system_status(api_auth_headers):

    client = TestClient(app)

    response = client.get("/system/status", headers=api_auth_headers["operator"])

    assert response.status_code == 200

    data = response.json()

    assert "status" in data
    assert "workers" in data
    assert "queue" in data
    assert "memory" in data
    assert "events" in data


def test_system_summary(api_auth_headers):

    client = TestClient(app)

    response = client.get("/system/summary", headers=api_auth_headers["operator"])

    assert response.status_code == 200

    data = response.json()

    assert "version" in data
    assert "uptime" in data
    assert "executions" in data


def test_system_workers(api_auth_headers):

    client = TestClient(app)

    response = client.get("/system/workers", headers=api_auth_headers["operator"])

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)


def test_system_queue(api_auth_headers):

    client = TestClient(app)

    response = client.get("/system/queue", headers=api_auth_headers["operator"])

    assert response.status_code == 200

    data = response.json()

    assert "pending" in data
    assert "running" in data
    assert "completed" in data
    assert "failed" in data


def test_system_memory(api_auth_headers):

    client = TestClient(app)

    response = client.get("/system/memory", headers=api_auth_headers["operator"])

    assert response.status_code == 200

    data = response.json()

    assert "items" in data


def test_system_events(api_auth_headers):

    client = TestClient(app)

    response = client.get("/system/events", headers=api_auth_headers["operator"])

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)


def test_system_executions(api_auth_headers):

    client = TestClient(app)

    response = client.get("/system/executions", headers=api_auth_headers["operator"])

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)

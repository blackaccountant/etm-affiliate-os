from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_system_status():

    response = client.get("/system/status")

    assert response.status_code == 200

    data = response.json()

    assert "status" in data
    assert "workers" in data
    assert "queue" in data
    assert "memory" in data
    assert "events" in data


def test_system_summary():

    response = client.get("/system/summary")

    assert response.status_code == 200

    data = response.json()

    assert "version" in data
    assert "uptime" in data
    assert "executions" in data


def test_system_workers():

    response = client.get("/system/workers")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)


def test_system_queue():

    response = client.get("/system/queue")

    assert response.status_code == 200

    data = response.json()

    assert "pending" in data
    assert "running" in data
    assert "completed" in data
    assert "failed" in data


def test_system_memory():

    response = client.get("/system/memory")

    assert response.status_code == 200

    data = response.json()

    assert "items" in data


def test_system_events():

    response = client.get("/system/events")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)


def test_system_executions():

    response = client.get("/system/executions")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
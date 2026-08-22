from app.system.intelligence import SystemIntelligence


def test_system_status():

    brain = SystemIntelligence()

    status = brain.system_status()

    assert status["status"] == "ONLINE"


def test_health():

    brain = SystemIntelligence()

    assert brain.health()["healthy"] is True


def test_summary():

    brain = SystemIntelligence()

    summary = brain.summary()

    assert "operational" in summary["message"].lower()
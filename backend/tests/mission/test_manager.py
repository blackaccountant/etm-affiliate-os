from app.mission.manager import MissionManager
from app.models.mission_record import MissionRecord
from app.workforce.manager import WorkforceManager
from app.workforce.worker_info import WorkerInfo
from app.workflow_engine.workflow_result import WorkflowResult


class SuccessfulEngine:
    def run(self, workflow_name, payload):
        return WorkflowResult(success=True, workflow=workflow_name, data={"test": True})


def test_manager_construction_does_not_create_a_session(monkeypatch):
    calls = []
    monkeypatch.setattr("app.mission.manager.SessionLocal", lambda: calls.append(True))
    MissionManager()
    assert calls == []


def test_create_mission_uses_isolated_session(db_session_factory):
    manager = MissionManager(session_factory=db_session_factory)
    mission = manager.create_mission("Affiliate Discovery", "Find products", "affiliate_discovery")
    session = db_session_factory()
    try:
        assert session.get(MissionRecord, mission.id) is not None
    finally:
        session.close()


def test_launch_uses_isolated_session(db_session_factory):
    workforce = WorkforceManager()
    workforce.register(WorkerInfo("Product Hunter", "Research", status="ONLINE"))
    manager = MissionManager(workforce=workforce, session_factory=db_session_factory)
    manager.executor.engine = SuccessfulEngine()
    launch = manager.launch("Affiliate Discovery", "Find products", "affiliate_discovery")
    assert launch["result"].success is True
    assert launch["worker"].status == "ONLINE"


def test_operation_sessions_are_separate_and_closed(db_session_factory):
    sessions = []

    def factory():
        session = db_session_factory()
        sessions.append(session)
        return session

    manager = MissionManager(session_factory=factory)
    manager.create_mission("One", "Test", "workflow")
    manager.create_mission("Two", "Test", "workflow")

    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]


def test_failed_operation_rolls_back_and_closes():
    class FailingSession:
        rolled_back = False
        closed = False

        def add(self, value):
            pass

        def commit(self):
            raise RuntimeError("persistence failed")

        def rollback(self):
            self.rolled_back = True

        def close(self):
            self.closed = True

    session = FailingSession()
    manager = MissionManager(session_factory=lambda: session)

    import pytest
    with pytest.raises(RuntimeError, match="persistence failed"):
        manager.create_mission("Failure", "Test", "workflow")

    assert session.rolled_back is True
    assert session.closed is True

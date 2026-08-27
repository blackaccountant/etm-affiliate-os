from app.mission.manager import MissionManager
from app.workforce.manager import WorkforceManager
from app.workforce.worker_info import WorkerInfo
from app.workflow_engine.workflow_result import WorkflowResult


class FakeSession:
    def __init__(self):
        self.added = []
        self.committed = False
        self.closed = False

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.committed = True

    def refresh(self, value):
        pass

    def close(self):
        self.closed = True


class SuccessfulWorkflowEngine:
    def __init__(self):
        self.calls = []

    def run(self, workflow_name, payload):
        self.calls.append((workflow_name, payload))
        return WorkflowResult(
            success=True,
            workflow=workflow_name,
            data={"products": [{"company": "Example"}]},
        )


def test_launch_mission(monkeypatch):
    workforce = WorkforceManager()
    workforce.register(
        WorkerInfo(
            name="Product Hunter",
            worker_type="Research",
            status="ONLINE",
        )
    )

    session = FakeSession()
    engine = SuccessfulWorkflowEngine()
    monkeypatch.setattr(
        "app.mission.manager.SessionLocal",
        lambda: session,
    )
    manager = MissionManager(workforce=workforce)
    manager.executor.engine = engine
    launch = manager.launch(
        name="Affiliate Discovery",
        objective="Find profitable affiliate products",
        workflow="affiliate_discovery",
    )

    assert launch["mission"] is not None
    assert launch["worker"] is not None
    assert (
        launch["worker"].status
        ==
        "BUSY"
    )
    assert launch["result"].success is True
    assert engine.calls == [("affiliate_discovery", {})]
    assert len(session.added) == 1
    assert session.committed is True
    assert session.closed is True

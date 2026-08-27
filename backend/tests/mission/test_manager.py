from app.mission.manager import MissionManager
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


def test_manager_creation():

    manager = MissionManager()

    assert manager is not None



def test_create_mission():

    manager = MissionManager()

    mission = manager.create_mission(
        name="Affiliate Discovery",
        objective="Find products",
        workflow="affiliate_discovery",
        metadata={
            "url": "https://openrouter.ai"
        },
    )

    assert mission.name == "Affiliate Discovery"
    assert mission.workflow == "affiliate_discovery"



def test_execute_mission(monkeypatch):
    manager = MissionManager()
    session = FakeSession()
    workflow_result = WorkflowResult(
        success=True,
        workflow="affiliate_discovery",
        data={"products": [{"company": "Example"}]},
    )
    executed_tasks = []

    def execute(task):
        executed_tasks.append(task)
        return workflow_result

    monkeypatch.setattr(
        "app.mission.manager.SessionLocal",
        lambda: session,
    )
    monkeypatch.setattr(manager.executor, "execute", execute)
    mission = manager.create_mission(
        name="Affiliate Discovery",
        objective="Find products",
        workflow="affiliate_discovery",
        metadata={
            "url": "https://example.invalid"
        },
    )

    result = manager.execute(
        mission
    )

    assert result.success is True
    assert result.data is workflow_result
    assert len(executed_tasks) == 1
    assert executed_tasks[0].workflow_name == "affiliate_discovery"
    assert executed_tasks[0].payload == {"url": "https://example.invalid"}
    assert session.committed is True
    assert session.closed is True



def test_clear():

    manager = MissionManager()

    manager.clear()

    assert len(
        manager.missions()
    ) == 0

from app.mission.manager import MissionManager
from app.models.execution import Execution
from app.models.mission_record import MissionRecord
from app.workforce.manager import WorkforceManager
from app.workforce.worker_info import WorkerInfo
from app.workflow_engine.workflow_result import WorkflowResult


class InspectingEngine:
    def __init__(self, session_factory):
        self.session_factory = session_factory
        self.observed = None

    def run(self, workflow_name, payload):
        session = self.session_factory()
        try:
            self.observed = (session.query(MissionRecord).one().status, session.query(Execution).one().status)
        finally:
            session.close()
        return WorkflowResult(success=True, workflow=workflow_name, data={"test": True})


def test_launch_mission_persists_before_workflow(db_session_factory):
    workforce = WorkforceManager()
    workforce.register(WorkerInfo("Product Hunter", "Research", status="ONLINE"))
    manager = MissionManager(workforce=workforce, session_factory=db_session_factory)
    engine = InspectingEngine(db_session_factory)
    manager.executor.engine = engine
    launch = manager.launch("Affiliate Discovery", "Find products", "affiliate_discovery")
    assert engine.observed == ("RUNNING", "RUNNING")
    assert launch["result"].success is True

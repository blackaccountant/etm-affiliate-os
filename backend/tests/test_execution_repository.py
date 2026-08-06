from app.models.execution import Execution


def test_execution_model_exists():

    assert Execution.__tablename__ == "executions"
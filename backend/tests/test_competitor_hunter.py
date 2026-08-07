

from app.ai.workers.competitor_hunter import CompetitorHunterWorker



def test_worker_creation():

    worker = CompetitorHunterWorker()

    assert worker.name == "CompetitorHunter"


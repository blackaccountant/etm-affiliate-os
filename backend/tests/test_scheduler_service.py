from app.scheduler.service import SchedulerService


def test_scheduler_service_creation():

    service = SchedulerService()

    assert service is not None


def test_scheduler_process_runs():

    service = SchedulerService()

    service.process()
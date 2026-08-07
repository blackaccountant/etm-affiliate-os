from app.system.dashboard import DashboardService


class FakeRuntime:

    def get_workers(self):

        return [
            {
                "name": "Product Hunter",
                "status": "ONLINE",
            }
        ]

    def get_history(self):

        return [
            {
                "workflow": "affiliate_discovery",
                "status": "SUCCESS",
                "duration": 1.5,
            }
        ]

    def get_events(self):

        return [
            "Affiliate Discovery Completed"
        ]

    def get_queue_status(self):

        return {
            "pending": 0,
            "running": 0,
            "completed": 1,
            "failed": 0,
        }

    def get_memory_count(self):

        return 0


def test_dashboard_summary():

    service = DashboardService(
        FakeRuntime()
    )

    data = service.summary()

    assert data["status"] == "ONLINE"

    assert data["workers"] == 1

    assert data["completed_missions"] == 1

    assert data["events"] == 1

    assert (
        data["latest_event"]
        ==
        "Affiliate Discovery Completed"
    )
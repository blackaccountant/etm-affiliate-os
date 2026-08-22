from app.system.dashboard import DashboardService


class IntelligenceRuntime:

    def get_workers(self):

        return []


    def get_history(self):

        return []


    def get_events(self):

        return []


    def get_queue_status(self):

        return {
            "pending": 0,
            "running": 0,
            "completed": 0,
            "failed": 0,
        }


    def get_memory_count(self):

        return 1


    def get_latest_mission_result(self):

        return {
            "workflow": "product_discovery",
            "success": True,
            "data": {
                "products": [
                    {
                        "name": "AI Writing Assistant",
                        "opportunity_score": 8.5,
                    }
                ]
            },
        }



def test_dashboard_exposes_mission_intelligence():

    dashboard = DashboardService(
        IntelligenceRuntime()
    )


    data = dashboard.summary()


    assert (
        data["latest_mission_result"]
        is not None
    )


    assert (
        data["latest_mission_result"]["workflow"]
        ==
        "product_discovery"
    )


    assert (
        len(
            data["latest_mission_result"]["data"]["products"]
        )
        ==
        1
    )
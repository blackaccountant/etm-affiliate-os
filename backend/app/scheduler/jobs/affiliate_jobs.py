from app.scheduler.job import Job


def product_discovery_job():

    return Job(
        name="daily_product_discovery",

        workflow_name="affiliate_discovery",

        payload={
            "url": "https://openrouter.ai"
        },

        interval_seconds=3600,
    )
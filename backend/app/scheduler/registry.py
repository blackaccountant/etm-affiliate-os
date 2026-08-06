"""
Job Registry

Keeps track of all scheduled jobs.
"""

from app.scheduler.jobs.affiliate_jobs import product_discovery_job


class JobRegistry:

    def __init__(self):

        self._jobs = {
            "daily_product_discovery": product_discovery_job(),
        }

    def get(self, name):

        return self._jobs.get(name)

    def all(self):

        return list(self._jobs.values())

    def register(self, job):

        self._jobs[job.name] = job
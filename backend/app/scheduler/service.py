import time

from app.scheduler.scheduler import Scheduler
from app.scheduler.registry import JobRegistry
from app.executor.executor import TaskExecutor


class SchedulerService:

    def __init__(self):

        self.scheduler = Scheduler()

        self.registry = JobRegistry()

        self.executor = TaskExecutor()

        self.running = False

    def process(self):

        for job in self.registry.all():

            task = self.scheduler.schedule(
                workflow_name=job.workflow_name,
                payload=job.payload,
            )

            queued_task = self.scheduler.next_task()

            if queued_task:

                self.executor.execute(
                    queued_task
                )

    def start(self):

        self.running = True

        while self.running:

            self.process()

            time.sleep(60)

    def stop(self):

        self.running = False
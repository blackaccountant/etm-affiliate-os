"""
Execution Status Definitions

Lifecycle states for ETM Affiliate OS workflows.
"""


from enum import Enum


class ExecutionStatus(str, Enum):

    CREATED = "CREATED"

    QUEUED = "QUEUED"

    RUNNING = "RUNNING"

    RESEARCHING = "RESEARCHING"

    ANALYZING = "ANALYZING"

    SCORING = "SCORING"

    SAVING = "SAVING"

    COMPLETED = "COMPLETED"

    FAILED = "FAILED"
"""
Workflow Result

Standard result object for every workflow.
"""

from dataclasses import dataclass, field


@dataclass
class WorkflowResult:

    success: bool

    workflow: str

    data: dict = field(default_factory=dict)

    events: list = field(default_factory=list)

    errors: list = field(default_factory=list)

    duration: float = 0.0
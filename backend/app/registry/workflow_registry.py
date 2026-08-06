"""
Workflow Registry

Central registry for available workflows.
"""


class WorkflowRegistry:

    def __init__(self):

        self._workflows = {}


    def register(
        self,
        name: str,
        workflow,
    ):

        self._workflows[name] = workflow


    def get(self, name: str):

        return self._workflows.get(name)


    def all(self):

        return self._workflows
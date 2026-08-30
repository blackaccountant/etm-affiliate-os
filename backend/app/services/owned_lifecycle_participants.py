"""Trusted runtime registry for optional owned-lifecycle participants."""

from typing import Protocol


class OwnedLifecycleParticipant(Protocol):
    def apply(self, db, authority, action: str, result) -> None: ...


class OwnedLifecycleParticipantRegistry:
    def __init__(self):
        self._participants = {}

    def register(self, workflow_name: str, participant: OwnedLifecycleParticipant) -> None:
        if workflow_name in self._participants:
            raise ValueError(f"lifecycle participant already registered for {workflow_name}")
        self._participants[workflow_name] = participant

    def get(self, workflow_name: str):
        return self._participants.get(workflow_name)


_registry = OwnedLifecycleParticipantRegistry()


def participant_for_workflow(workflow_name: str):
    return _registry.get(workflow_name)


def register_default_participants() -> None:
    if _registry.get("distribution_publish") is None:
        from app.distribution.distribution_publish_lifecycle_participant import DistributionPublishLifecycleParticipant
        _registry.register("distribution_publish", DistributionPublishLifecycleParticipant())
    if _registry.get("distribution_reconcile") is None:
        from app.distribution.distribution_reconcile_lifecycle_participant import DistributionReconcileLifecycleParticipant
        _registry.register("distribution_reconcile", DistributionReconcileLifecycleParticipant())


register_default_participants()

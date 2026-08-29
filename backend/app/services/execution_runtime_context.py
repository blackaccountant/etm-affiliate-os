"""Trusted, non-serialized context for one active workflow invocation."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator

from app.services.execution_lease import ExecutionLeaseAuthority


@dataclass(frozen=True)
class ExecutionRuntimeContext:
    """Authority supplied by orchestration, never by a durable workflow payload."""

    authority: ExecutionLeaseAuthority
    mission_id: str
    is_recovery: bool = False


_current_context: ContextVar[ExecutionRuntimeContext | None] = ContextVar(
    "execution_runtime_context", default=None,
)


@contextmanager
def activate_execution_runtime_context(
    context: ExecutionRuntimeContext,
) -> Iterator[None]:
    token = _current_context.set(context)
    try:
        yield
    finally:
        _current_context.reset(token)


def current_execution_runtime_context() -> ExecutionRuntimeContext | None:
    return _current_context.get()

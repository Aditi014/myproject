"""Caps the total number of agent invocations for a single user request
(spec requirement: max 10, to prevent infinite retry/re-invocation loops)."""

from __future__ import annotations


class InvocationBudget:
    def __init__(self, max_invocations: int = 10):
        self.max_invocations = max_invocations
        self.used = 0

    def consume(self) -> bool:
        """Returns True and counts one invocation if budget remains, else
        returns False without counting."""
        if self.used >= self.max_invocations:
            return False
        self.used += 1
        return True

    def remaining(self) -> int:
        return self.max_invocations - self.used

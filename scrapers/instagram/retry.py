from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int

    def attempts(self) -> range:
        return range(1, self.max_attempts + 1)

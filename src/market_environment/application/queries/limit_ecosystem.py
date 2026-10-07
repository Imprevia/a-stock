"""Provider-free limit ecosystem composition over explicit local repositories."""

from __future__ import annotations

import copy
from collections.abc import Callable
from datetime import date
from typing import Any

from ...domain.policies.limits import apply_promotion_quality_layer


class LimitEcosystemComposer:
    def __init__(
        self,
        repository: Any,
        *,
        enabled: Callable[[], bool],
        strip_disabled_fields: Callable[[dict[str, Any]], dict[str, Any]],
        build_ecosystem: Callable[[Any, date, dict[str, Any]], dict[str, Any]],
        validate: Callable[[dict[str, Any]], dict[str, Any]],
        checksum: Callable[[dict[str, Any]], str],
        max_cache_entries: int = 32,
    ) -> None:
        self.repository = repository
        self.enabled = enabled
        self.strip_disabled_fields = strip_disabled_fields
        self.build_ecosystem = build_ecosystem
        self.validate = validate
        self.checksum = checksum
        self.max_cache_entries = max_cache_entries
        self.cache: dict[tuple[str, bool, str, str], dict[str, Any]] = {}

    def compose(self, as_of: date, payload: dict[str, Any]) -> dict[str, Any]:
        value = copy.deepcopy(payload)
        enabled = self.enabled()
        if not enabled:
            value = self.strip_disabled_fields(value)
            for field in (
                "ladder",
                "stratifications",
                "history",
                "ruleEvidence",
                "riskEvidence",
                "confirmation",
                "invalidation",
            ):
                value.pop(field, None)
        elif self.repository is not None:
            cache_key = (
                as_of.isoformat(),
                enabled,
                self.checksum(value),
                self.repository.materialization_revision(as_of),
            )
            cached = self.cache.get(cache_key)
            if cached is not None:
                return copy.deepcopy(cached)
            value = self.build_ecosystem(self.repository, as_of, value)
            value = apply_promotion_quality_layer(value)
            result = self.validate(value)
            self.cache[cache_key] = copy.deepcopy(result)
            if len(self.cache) > self.max_cache_entries:
                self.cache.pop(next(iter(self.cache)))
            return result
        return self.validate(value)


__all__ = ["LimitEcosystemComposer"]

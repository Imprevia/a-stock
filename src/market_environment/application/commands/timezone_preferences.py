"""Timezone preference update use case."""

from __future__ import annotations

from dataclasses import dataclass

from ..ports import TimezonePreferenceWriter


@dataclass(frozen=True, slots=True)
class UpdateTimezonePreferenceCommand:
    preferences: TimezonePreferenceWriter

    def execute(
        self,
        scope: str,
        *,
        subject_id: str,
        workspace_id: str,
        timezone_value: str | None,
        actor_id: str,
    ):
        return self.preferences.set(
            scope,
            subject_id=subject_id,
            workspace_id=workspace_id,
            timezone_value=timezone_value,
            actor_id=actor_id,
        )


__all__ = ["UpdateTimezonePreferenceCommand"]

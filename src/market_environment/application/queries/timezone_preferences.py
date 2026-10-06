"""Timezone preference read use case."""

from __future__ import annotations

from dataclasses import dataclass

from ..ports import TimezonePreferenceReader


@dataclass(frozen=True, slots=True)
class GetTimezonePreferenceQuery:
    preferences: TimezonePreferenceReader

    def execute(
        self,
        scope: str,
        *,
        subject_id: str,
        workspace_id: str,
    ):
        return self.preferences.get(
            scope,
            subject_id=subject_id,
            workspace_id=workspace_id,
        )


__all__ = ["GetTimezonePreferenceQuery"]

"""Provider-free collection status read use cases."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import date
from typing import Any

from ..ports import CollectionStatusReader


@dataclass(frozen=True, slots=True)
class GetCollectionStatusQuery:
    status_reader: CollectionStatusReader

    def execute(self, as_of: date) -> dict[str, Any]:
        result = copy.deepcopy(dict(self.status_reader.collection_status(as_of)))
        actual = result.get("asOf")
        if actual not in (as_of, as_of.isoformat()):
            raise RuntimeError(
                f"collection status date {actual} does not match requested date "
                f"{as_of.isoformat()}"
            )
        return result


@dataclass(frozen=True, slots=True)
class GetCollectionRunStatusQuery:
    status_reader: CollectionStatusReader

    def execute(self, run_id: str):
        return copy.deepcopy(self.status_reader.get_run(run_id))


__all__ = ["GetCollectionRunStatusQuery", "GetCollectionStatusQuery"]

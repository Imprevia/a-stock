"""Dataset committers backed by the shared persistence unit of work."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone

from ...application.ports import MarketEnvironmentUnitOfWork
from ...application.ports.committers import (
    DatasetCommitEvidence,
    DatasetCommitRequest,
)
from ...application.ports.limits_committers import (
    LimitsCommitEvidence,
    LimitsCommitRequest,
    LimitsManifestEvidence,
)
from ...domain.models import DATASET_IDS, CollectionCandidate, CollectionTaskState
from ...snapshot_store import LIMIT_DETAIL_CHECKSUM_KEY, payload_checksum


STANDARD_SNAPSHOT_DATASETS = frozenset({"breadth", "sectors", "activeDirection"})


class StandardSnapshotCommitter:
    """Commit one normalized candidate as a fenced exact-date snapshot."""

    def __init__(
        self,
        dataset_id: str,
        unit_of_work_factory: Callable[[], MarketEnvironmentUnitOfWork],
    ) -> None:
        if dataset_id not in DATASET_IDS:
            raise ValueError(f"unsupported standard snapshot committer: {dataset_id}")
        if dataset_id not in STANDARD_SNAPSHOT_DATASETS:
            raise ValueError(f"dataset requires a specialized committer: {dataset_id}")
        self.dataset_id = dataset_id
        self._unit_of_work_factory = unit_of_work_factory

    def commit(self, request: DatasetCommitRequest) -> DatasetCommitEvidence:
        if request.identity.dataset != self.dataset_id:
            raise ValueError(
                "dataset committer identity mismatch: "
                f"expected {self.dataset_id}, received {request.identity.dataset}"
            )
        if request.outcome.state is CollectionTaskState.FAILED_RETAINED:
            raise ValueError("standard committer cannot commit retained failures")

        with self._unit_of_work_factory() as unit_of_work:
            stored = unit_of_work.leases.execute_fenced(
                request.lease,
                "snapshot_commit",
                lambda _connection: unit_of_work.snapshots.put(request.candidate),
                expected_identity=request.identity,
            )
            if not isinstance(stored, CollectionCandidate):
                raise TypeError("snapshot repository returned invalid commit evidence")
            if stored.identity != request.identity:
                raise ValueError("snapshot repository returned mismatched commit identity")
            unit_of_work.commit()

        return DatasetCommitEvidence(
            identity=request.identity,
            outcome_state=request.outcome.state,
            candidate=stored,
            writes=("snapshot",),
        )


class LimitsDatasetCommitter:
    """Atomically commit the limits snapshot, fact set, and manifest."""

    dataset_id = "limits"

    def __init__(
        self,
        unit_of_work_factory: Callable[[], MarketEnvironmentUnitOfWork],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now = now or (lambda: datetime.now(timezone.utc))

    def commit(self, request: DatasetCommitRequest) -> LimitsCommitEvidence:
        if not isinstance(request, LimitsCommitRequest):
            raise TypeError("limits committer requires LimitsCommitRequest")
        if request.outcome.state is CollectionTaskState.FAILED_RETAINED:
            raise ValueError("limits committer cannot commit retained failures")

        normalization = request.normalization.normalized()
        fetched_at = (
            normalization.rows[0].fetched_at
            if normalization.rows
            else request.candidate.fetched_at or self._now()
        )
        actual_as_of = normalization.actual_as_of
        assert actual_as_of is not None
        manifest = self._manifest(normalization, fetched_at=fetched_at)
        candidate = self._with_detail_checksum(
            request.candidate,
            manifest.dataset_checksum,
        )
        previous_manifest = None
        previous_candidate = request.previous_candidate
        previous_normalization = request.previous_normalization
        if previous_candidate is not None:
            if previous_normalization is None or request.previous_lease is None:
                raise ValueError("limits previous commit bundle is incomplete")
            previous_fetched_at = (
                previous_normalization.rows[0].fetched_at
                if previous_normalization.rows
                else previous_candidate.fetched_at or self._now()
            )
            previous_manifest = self._manifest(
                previous_normalization,
                fetched_at=previous_fetched_at,
            )
            previous_candidate = self._with_detail_checksum(
                previous_candidate,
                previous_manifest.dataset_checksum,
            )

        with self._unit_of_work_factory() as unit_of_work:
            def write(_connection: object) -> CollectionCandidate:
                if (
                    previous_candidate is not None
                    and previous_normalization is not None
                    and request.previous_lease is not None
                ):
                    def write_previous(_nested_connection: object) -> None:
                        unit_of_work.limit_details.put_limit_detail(
                            request.previous_lease.as_of,
                            previous_manifest.as_mapping(),
                            previous_normalization.rows,
                        )
                        unit_of_work.snapshots.put(previous_candidate)

                    unit_of_work.leases.execute_fenced(
                        request.previous_lease,
                        "limits_previous_collection_commit",
                        write_previous,
                        expected_identity=previous_candidate.identity,
                    )
                unit_of_work.limit_details.put_limit_detail(
                    request.identity.as_of,
                    manifest.as_mapping(),
                    normalization.rows,
                )
                return unit_of_work.snapshots.put(candidate)

            stored = unit_of_work.leases.execute_fenced(
                request.lease,
                "limits_collection_commit",
                write,
                expected_identity=request.identity,
            )
            if not isinstance(stored, CollectionCandidate):
                raise TypeError("snapshot repository returned invalid limits evidence")
            if stored.identity != request.identity:
                raise ValueError("snapshot repository returned mismatched limits identity")
            unit_of_work.commit()

        return LimitsCommitEvidence(
            identity=request.identity,
            outcome_state=request.outcome.state,
            candidate=stored,
            writes=("limit-facts", "limit-manifest", "snapshot"),
            manifest=manifest,
            fact_count=len(normalization.rows),
            previous_as_of=request.previous_as_of,
            previous_detail_available=request.previous_detail_available,
            snapshot_checksum=payload_checksum(stored.payload),
            previous_manifest=previous_manifest,
            previous_fact_count=(
                len(previous_normalization.rows)
                if previous_normalization is not None
                else None
            ),
        )

    @staticmethod
    def _manifest(
        normalization: LimitNormalizationResult,
        *,
        fetched_at: datetime,
    ) -> LimitsManifestEvidence:
        actual_as_of = normalization.actual_as_of
        assert actual_as_of is not None
        return LimitsManifestEvidence(
            as_of=normalization.as_of,
            actual_as_of=actual_as_of,
            source=normalization.source,
            source_revision=normalization.source_revision,
            rule_version=normalization.rule_version,
            complete=normalization.complete,
            membership_complete=normalization.membership_complete,
            streak_complete=normalization.streak_complete,
            pool_quality=normalization.pool_quality,
            excluded=normalization.excluded,
            warnings=normalization.warnings,
            dataset_checksum=normalization.dataset_checksum,
            fetched_at=fetched_at,
        )

    @staticmethod
    def _with_detail_checksum(
        candidate: CollectionCandidate,
        checksum: str,
    ) -> CollectionCandidate:
        payload = copy.deepcopy(dict(candidate.payload))
        quality_payload = payload.get("quality")
        if not isinstance(quality_payload, dict):
            raise ValueError("limits snapshot requires quality metadata")
        quality_payload[LIMIT_DETAIL_CHECKSUM_KEY] = checksum
        quality = candidate.quality
        if quality is not None:
            quality = replace(
                quality,
                extra={**copy.deepcopy(dict(quality.extra)), LIMIT_DETAIL_CHECKSUM_KEY: checksum},
            )
        return replace(candidate, payload=payload, quality=quality)


__all__ = [
    "LimitsDatasetCommitter",
    "STANDARD_SNAPSHOT_DATASETS",
    "StandardSnapshotCommitter",
]

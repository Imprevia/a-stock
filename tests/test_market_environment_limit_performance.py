from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from src.market_environment.collection import CollectionCoordinator
from src.market_environment.service import MARKET_TIME_ZONE
from tests.test_market_environment_limit_promotion import (
    CURRENT,
    PREVIOUS,
    DetailedLimitProvider,
    limit_result,
    seed_store,
)


def test_limit_collection_emits_structured_timings_and_warm_read_budget(tmp_path, caplog, monkeypatch) -> None:
    monkeypatch.setenv("MARKET_ENVIRONMENT_LIMITS_V1_ENABLED", "1")
    store, service = seed_store(tmp_path)
    provider = DetailedLimitProvider(
        {PREVIOUS: limit_result(PREVIOUS, ["600000", "600001"]), CURRENT: limit_result(CURRENT, ["600000"])}
    )
    coordinator = CollectionCoordinator(
        provider,
        store,
        now=lambda: datetime.combine(CURRENT, datetime.min.time(), tzinfo=MARKET_TIME_ZONE).replace(hour=16),
        rebuild_aggregate=service.rebuild_materialized_aggregate,
        limits_v1_enabled=True,
    )

    with caplog.at_level(logging.INFO, logger="src.market_environment"):
        result = coordinator.collect(CURRENT, ["limits"])

    assert result.run.status == "success"
    task = result.tasks[0]
    required_timings = {
        "previousLeaseWaitMs",
        "previousProviderCollectionMs",
        "previousStoreWriteMs",
        "providerCollectionMs",
        "storeWriteMs",
        "aggregateRebuildMs",
    }
    assert required_timings <= set(task.timings)
    assert all(float(task.timings[key]) >= 0 for key in required_timings)
    assert provider.calls == [PREVIOUS, CURRENT]

    collection_logs = [record for record in caplog.records if getattr(record, "event", None) == "limit_collection"]
    promotion_logs = [
        record for record in caplog.records if getattr(record, "event", None) == "limit_promotion_aggregation"
    ]
    assert collection_logs and promotion_logs
    collection_log = collection_logs[-1]
    promotion_log = promotion_logs[-1]
    assert collection_log.provider_calls == 2
    assert collection_log.requested_as_of == CURRENT.isoformat()
    assert collection_log.previous_as_of == PREVIOUS.isoformat()
    assert collection_log.dataset_checksum
    assert collection_log.phase_timings["providerCollectionMs"] >= 0
    assert task.timings["aggregateRebuildMs"] >= 0
    assert promotion_log.join_ms >= 0
    assert promotion_log.eligible_count == 2
    assert promotion_log.matched_count == 1

    encoded = json.dumps(service.get(CURRENT), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert len(encoded) > 0
    provider_calls_before_warm = list(provider.calls)
    elapsed_ms: list[float] = []
    for _ in range(100):
        started = time.perf_counter()
        payload = service.get(CURRENT)
        elapsed_ms.append((time.perf_counter() - started) * 1000)
        assert payload["chapter01"]["limits"]["promotionRatio"] == 0.5
    ordered = sorted(elapsed_ms)
    p95 = ordered[94]
    assert p95 < 500
    assert max(elapsed_ms) < 500
    assert provider.calls == provider_calls_before_warm

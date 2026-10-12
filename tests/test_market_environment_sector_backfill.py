from datetime import date, timedelta

from src.market_environment.application.commands.sector_continuity_backfill import (
    BackfillRequest,
    SectorContinuityBackfillService,
)
from src.market_environment import cli as market_cli
from src.market_environment.domain.analysis.sector_continuity import build_continuity_result
from src.market_environment.domain.models.sector_continuity import Lineage
from src.market_environment.domain.analysis.sector_continuity import analyze_candidates


AS_OF = date(2026, 10, 9)


class Repository:
    def __init__(self):
        self.results = {}
        self.attempts = []
        self.runs = []

    def put_result(self, result):
        self.results[result.as_of] = result

    def get_result(self, as_of, calculation_version=None):
        return self.results.get(as_of)

    def put_backfill_attempt(self, attempt):
        self.attempts.append(attempt)

    def put_backfill_run(self, run):
        self.runs.append(run)

    def list_result_dates(self, **_):
        return tuple(self.results)

    def list_backfill_attempts(self, run_id):
        return tuple(item for item in self.attempts if item.run_id == run_id)


def result(as_of):
    validation = analyze_candidates({})[1]
    return build_continuity_result(
        as_of=as_of,
        traces=(),
        candidates=(),
        validation=validation,
        lineage=Lineage(as_of, as_of, "fixture", "v1", 1, as_of.isoformat()),
    )


def test_backfill_uses_finite_authoritative_sessions_and_isolates_failure():
    sessions = (AS_OF - timedelta(days=2), AS_OF - timedelta(days=1), AS_OF)
    repository = Repository()

    def processor(as_of, revisions):
        if as_of == sessions[1]:
            raise RuntimeError("fixture gap")
        return result(as_of)

    service = SectorContinuityBackfillService(
        repository,
        session_reader=lambda as_of, count: sessions[-count:],
        processor=processor,
    )
    run = service.run(BackfillRequest(as_of=AS_OF, sessions=3, source_revisions={"membership": "v1"}))
    assert run.status == "partial"
    assert [attempt.status for attempt in run.attempts] == ["insufficient", "failed-missing", "insufficient"]
    assert set(repository.results) == {sessions[0], sessions[2]}


def test_readiness_is_provider_free_and_reports_missing_sessions():
    sessions = (AS_OF - timedelta(days=1), AS_OF)
    repository = Repository()
    repository.results[AS_OF] = result(AS_OF)
    service = SectorContinuityBackfillService(
        repository,
        session_reader=lambda as_of, count: sessions,
        processor=lambda as_of, revisions: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    readiness = service.readiness(AS_OF, required_history=2)
    assert readiness.available_history == 1
    assert readiness.missing_sessions == (sessions[0],)
    assert readiness.coverage == 0.5


def test_backfill_cli_is_explicit_bounded_dry_run_and_never_adds_collection_dataset(capsys):
    code = market_cli.main([
        "sector-continuity", "backfill",
        "--as-of", AS_OF.isoformat(),
        "--sessions", "3",
        "--session-date", (AS_OF - timedelta(days=2)).isoformat(),
        "--session-date", (AS_OF - timedelta(days=1)).isoformat(),
        "--session-date", AS_OF.isoformat(),
        "--calculation-version", "calc-v1",
        "--source-revision", "membership=v1",
    ])
    assert code == 0
    payload = __import__("json").loads(capsys.readouterr().out)
    assert payload["formalWrites"] == 0
    assert payload["providerCalls"] == 0


def test_resume_skips_successful_dates_but_retries_failed_dates():
    sessions = (AS_OF - timedelta(days=1), AS_OF)
    repository = Repository()
    calls = []

    def processor(as_of, revisions):
        calls.append(as_of)
        return result(as_of)

    service = SectorContinuityBackfillService(repository, session_reader=lambda *_: sessions, processor=processor)
    request = BackfillRequest(as_of=AS_OF, sessions=2, run_id="resume-1")
    first = service.run(request)
    repository.attempts = [
        __import__("dataclasses").replace(first.attempts[0], status="success"),
        __import__("dataclasses").replace(first.attempts[1], status="failed-missing"),
    ]
    calls.clear()
    service.run(request)
    assert calls == [AS_OF]

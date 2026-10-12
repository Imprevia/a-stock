## Why

The current sectors fallback chain ends at Fuyao (4 verified fields) once the Eastmoney and (planned) Tushare paths exhaust. When all four structured sources are gated, missing, or fail, the `sectors` task still reports `failed-missing` with no `name` / `changePct` / `amount` / leader facts at all. Two lightly allowlisted static HTML hosts (Sina and Xueqiu) can supply those web-visible facts without touching the structured sources, and the existing Scrapling static engine profile is precisely the engine-neutral contract that can ship them behind the same capability gate and composition root as every other provider.

This change is the **last** tier of the chain by design: it is default disabled, never short-circuits the structured tier, cannot synthesize the supplementary fields (`upCount`, `downCount`, `mainNet`, `mainNetPct`), and cannot promote itself without an authorized offline capability report.

## What Changes

- Add two independent `SourceAdapter` implementations under `src/market_environment/infrastructure/providers/sina_html/` and `xueqiu_html/` that read a single static HTML page per request via the existing Scrapling static engine and emit typed `SectorRow` data.
- Restrict the new adapters to the four web-visible fields (`code`, `name`, `changePct`, `amount`, `leader` as text); the four `SUPPLEMENTAL_FIELDS` (`mainNet`, `mainNetPct`, `upCount`, `downCount`) MUST remain `null` with structured warnings and MUST never be approximated from company count, volume, or any other numerically available value.
- Extend the existing fixed independent-provider fallback order to `push2 → push2delay → eastmoney-dataapi-enrichment (settled) → tushare-ths (if enabled) → fuyao-ths (if enabled) → sina-html → xueqiu-html`.
- Add a `crawlFallback` settings segment (`enabled=false` default, allowlist override) that decides whether the Scrapling engine is reachable and whether the two adapters are registered; `enabled=false` MUST cause zero I/O and adapter registration MUST be skipped entirely.
- Add capability revisions `crawl-html-sina-v1` and `crawl-html-xueqiu-v1`; runtime calls SHALL be refused unless a stored `eligible` report exists with a matching revision; a missing/non-eligible/mismatched report SHALL perform no network I/O.
- Add a probe subcommand `python -m src.market_environment.cli sectors probe --source {sina-html|xueqiu-html} [--allow-real]` that writes only an isolated SQLite store, never writes a formal snapshot, and refuses to run in production configuration without `--allow-real` and after-hours validation.
- Add Helm values `marketEnvironment.crawlFallback.enabled=false` and `marketEnvironment.crawlFallback.sources=["sina","xueqiu"]`, leaving `scheduledCollection` disabled and suspended.
- Document the chain extension in `docs/architecture.md` (data sources table + infrastructure section) and `docs/runbooks.md` (末层 HTML 静态源 small section), and add an active exec plan under `docs/exec-plans/active/`.

No database migration, no public HTTP route change, no `SectorRow` schema change, no frontend change, no automatic schedule activation, no real probe is executed by this change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `sector-data-collection-stability`: extend the fixed fallback order with the two opt-in static HTML sources at the very end, define the strict field authority (web-visible only) and null discipline, define the capability-gate / redacted-report contract for the HTML tier, and forbid the HTML tier from writing back into the Eastmoney enrichment path.

## Impact

- Affects `src/market_environment/infrastructure/providers/sectors_acquisition.py` (acquisition plan), new files under `infrastructure/providers/sina_html/` and `infrastructure/providers/xueqiu_html/`, `bootstrap/settings.py` and `bootstrap/container.py` (composition wiring), `interfaces/cli` (probe subcommand), `deploy/helm/a-stock/values.yaml` and chart templates, tests under `tests/`, fixtures under `tests/fixtures/sina_html/` and `tests/fixtures/xueqiu_html/` (offline synthetic), and documentation.
- Reuses the generic capability-promotion boundary delivered by `activate-fuyao-sector-fallback` and the transport contract delivered by `provider-http-transport`; this change adds no second promotion path and no independent transport policy.
- Adds no new public HTTP API, no PostgreSQL table, no frontend field, no browser, no Spider, no automatic engine escalation, and no production schedule activation.
- The `--allow-real` probe, capability report promotion, image/manifest rollout, and any single dataset collection remain separately authorized operational actions; this change does not perform them.

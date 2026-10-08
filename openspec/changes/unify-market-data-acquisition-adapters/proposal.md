## Why

The market-environment backend has unified host-level HTTP controls and five dataset collectors, but the runtime collectors still depend on a large legacy provider facade, inspect vendor-specific payloads, and return persistence-oriented task records instead of the typed collector outcome declared by the application port. This makes every new provider or transport option spread Eastmoney, Fuyao, TDX, Tencent, fallback, quality, and feature-gate differences into collection orchestration and prevents business workflows from consuming one stable acquisition contract.

## What Changes

- Introduce a typed market-data acquisition adapter contract that separates transport responses, vendor normalization, dataset acquisition plans, and collection outcomes.
- Require every provider adapter to return a normalized candidate or classified failure containing requested and actual dates, source/revision, observations, quality, warnings, timings, and redacted provenance.
- Close the existing `DatasetCollector.collect(DatasetDate) -> CollectionOutcome` boundary so collection orchestration owns task, lease, retention, commit, and aggregate rebuild behavior without reflecting over provider-specific collector methods.
- Replace the runtime inheritance from the legacy all-dataset provider facade with registered dataset acquisition plans and vendor adapters while preserving the current provider priority, feature flags, exact-date validation, shadow/enrichment behavior, and failure-retention semantics.
- Make the shared provider transport engine-neutral while retaining one authoritative host policy for pacing, request budgets, retries, `Retry-After`, single-flight, cache isolation, cooldown, and diagnostics.
- Keep the existing requests backend as the default and add an optional, host-allowlisted Scrapling HTTP backend for authorized sources that need HTTP/TLS fingerprint compatibility without JavaScript execution. Scrapling remains disabled by default and MUST NOT turn permission failures, CAPTCHA challenges, or unsupported dates into successful evidence.
- Add contract, architecture, fixture, and deployment tests proving equivalent normalized results and failure classifications across transport backends without changing public API responses.

## Capabilities

### New Capabilities

- `market-data-acquisition-adapters`: Defines the provider adapter registry, dataset acquisition plans, normalized candidate/failure envelope, capability policy, provenance, and vendor-independent collection boundary.

### Modified Capabilities

- `provider-http-transport`: Extends the shared transport contract to support registered request engines, including an optional Scrapling engine, while keeping the existing host policy and non-retryable permission semantics authoritative.
- `market-data-collection-management`: Requires collection orchestration to consume normalized collector outcomes and keep provider selection, fallback, and payload differences outside run/task, lease, retention, and materialization workflows.

## Impact

- Primary code impact: `src/market_environment/application/ports/`, `application/collection/`, `domain/models/`, `infrastructure/providers/`, `infrastructure/collection/`, `bootstrap/`, and the shared transport under `src/trading_system/data/`.
- The legacy `MarketDataProvider` runtime seam and compatibility adapters will be reduced incrementally; stable public imports remain until their callers are migrated and characterized.
- Existing HTTP paths, response fields, five dataset identifiers, PostgreSQL schema, exact-date snapshots, provider-free GET/status behavior, provider ordering, and default feature flags remain compatible.
- An optional Scrapling dependency profile may affect a dedicated runtime image, Helm resources, and runbook guidance. JavaScript/browser-backed collection, browser installation, remote CDP, and a browser worker remain follow-up work requiring a separate resource and security decision.
- The in-progress Fuyao sector enrichment rollout remains behaviorally unchanged; this change must preserve its field authority, latest-only gate, approved revision, and default-disabled configuration.
- No proxy pool, credential fabrication, CAPTCHA/access-control bypass, automatic 403 escalation, production provider probe, schedule activation, or production deployment is authorized by this proposal.

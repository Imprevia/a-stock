## ADDED Requirements

### Requirement: Static HTML sources extend the sectors fallback order with web-visible facts only
The system MAY extend the sectors fallback order with up to two independent static HTML sources: `sectors-sina-html` and `sectors-xueqiu-html`. They sit strictly **after** any approved Fuyao THS step and never before it. The combined order is therefore `push2 → push2delay → eastmoney-dataapi-enrichment (settled) → tushare-ths (if enabled) → fuyao-ths (if enabled) → sina-html → xueqiu-html`. Each HTML source SHALL be registered as a separate `SourceAdapter` with its own capability revision (`crawl-html-sina-v1` / `crawl-html-xueqiu-v1`), its own redacted probe report, and SHALL be reachable only through the existing Scrapling static engine. The HTML sources SHALL never write back into the Eastmoney `dataapi/bkzj/getbkzj` enrichment path and SHALL never produce supplementary field values. They MUST NOT be invoked when `marketEnvironment.crawlFallback.enabled=false` (or its `MARKET_ENVIRONMENT_CRAWL_FALLBACK_ENABLED=0` equivalent), when the matching report is missing, when the report status is not `eligible`, when the stored revision differs from `crawl-html-<host>-v1`, or when the request's `sourceId` is not on the engine's allowlist for the configured host.

#### Scenario: HTML tier is invoked only after every eligible structured source fails
- **WHEN** the Eastmoney pair, the dataapi enrichment step, the Tushare step (if enabled), and the Fuyao step (if enabled) all return classified failures or are unsatisfiable, and `marketEnvironment.crawlFallback.enabled=true` is set with matching eligible reports for `sina-html` and `xueqiu-html`
- **THEN** the collector proceeds to `sectors-sina-html`; only when that returns a classified failure does it proceed to `sectors-xueqiu-html`; `sectors-sina-html` success short-circuits `sectors-xueqiu-html` exactly the same way every higher tier does

#### Scenario: HTML tier is disabled or capability-gate unsatisfied
- **WHEN** `marketEnvironment.crawlFallback.enabled=false`, the matching report is missing, the report status is not `eligible`, or the configured revision does not match
- **THEN** the corresponding HTML source SHALL perform zero network I/O and SHALL be skipped; the existing failed-retained/failed-missing semantics from the previous tier remain authoritative

#### Scenario: HTML tier is disabled when `scheduledCollection` is enabled
- **WHEN** an operator enables `marketEnvironment.scheduledCollection.enabled=true` while leaving `marketEnvironment.crawlFallback.enabled=false`
- **THEN** the collector SHALL NOT add HTML sources to the scheduled plan, and any UI surface SHALL display the HTML tier as `disabled` with no link to a capability report

### Requirement: Static HTML source field authority is web-visible only
The system SHALL map a static HTML source payload to the `SectorRow` schema using only the four web-visible facts that the rendered card exposes: `code` (derived from the page identifier), `name` (the card heading text), `changePct` (the card percentage text parsed as a float), `amount` (the card turnover text parsed as float and unit-normalized to yuan), and `leader` (the leader string text only when the card exposes a leader text label, never a numeric or code identifier). The supplementary fields `mainNet`, `mainNetPct`, `upCount`, `downCount` SHALL always be `null` for HTML-source rows. The system SHALL NOT derive any of those supplementary fields from page facts such as the number of constituent rows, an average numeric, a count of green/red cells, the count of listed stocks on the page, or any other semantically different value exposed by the page. A `leader` value SHALL be the leader display string; the underlying leader identifier (when present in the page) SHALL be retained only as redacted provenance and SHALL NOT be written into the `leader` field.

#### Scenario: Web-visible fields are present and supplementary fields are absent
- **WHEN** an HTML card text exposes a name, percentage, turnover figure, and leader text label
- **THEN** the row exposes `code`, `name`, `changePct`, `amount`, and `leader` (as text), leaves `mainNet`, `mainNetPct`, `upCount`, and `downCount` as `null`, and records a structured `dom-source-unsupported` warning for each null field

#### Scenario: Supplementary facts appear on the page but are forbidden
- **WHEN** the rendered HTML page contains a numeric field that resembles a breadth or fund-flow value (for example, a count of constituent rows, an embedded summary number, or a labelled `inflow` text)
- **THEN** the adapter MUST NOT promote that value into `mainNet`, `mainNetPct`, `upCount`, or `downCount`; the forbidden promotion SHALL be covered by a unit test that wires a synthetic page containing such numbers and asserts all four supplementary fields remain `null`

#### Scenario: Leader identifier must not appear as leader text
- **WHEN** an HTML row contains a leader identifier (for example a stock code) in a slot where the leader name is expected
- **THEN** the adapter SHALL leave the `leader` field `null` and SHALL emit a `leader-identifier-not-name` warning; the same rule applies when the card only exposes a numeric badge that could be misinterpreted as a leader name

### Requirement: Static HTML source transport is fail-closed and capability-gated
The system SHALL send every HTML-tier request through the existing Scrapling static engine, one bodyless GET per request. The adapter SHALL NOT create its own `requests.Session`, SHALL NOT retry on its own, SHALL NOT escalate to any other engine, and SHALL NOT execute browser code, browser install, JavaScript rendering, or challenge solving. When the engine returns HTTP 401/403, when the response body is an HTML interstitial that the engine classifies as login wall / CAPTCHA / interstitial challenge, or when the engine itself reports a transport or classification failure, the adapter SHALL classify the attempt as `permission` or `challenge` non-retryable, SHALL emit a `host-permission-denied` or `host-challenge-detected` warning, SHALL NOT retry, SHALL NOT silently fall back to a different host, and SHALL continue to the next tier in the chain.

#### Scenario: HTML host returns HTTP 401 or 403
- **WHEN** the Scrapling engine returns HTTP 401 or 403 from an HTML host
- **THEN** the adapter SHALL classify the attempt as non-retryable permission failure and SHALL continue to the next tier; the engine SHALL NOT be re-entered for that source within the same request

#### Scenario: HTML host returns a login wall or challenge interstitial
- **WHEN** the Scrapling engine reports a login wall, CAPTCHA, interstitial challenge, or otherwise classifies the response as `challenge`
- **THEN** the adapter SHALL treat it as a non-retryable challenge failure and SHALL continue to the next tier; no `mainNet`, `mainNetPct`, `upCount`, or `downCount` value SHALL be derived from any number visible in the interstitial body

#### Scenario: HTML page structure drifts from the captured fixture
- **WHEN** the rendered HTML returns a successful 200 response but the selector footprint no longer matches the captured fixture's expected text/structure beyond a documented tolerance
- **THEN** the adapter SHALL emit a `dom-drift` warning, SHALL mark the candidate as `fallback` or `degraded` quality, and SHALL NOT silently fabricate `name`, `changePct`, `amount`, or `leader` from unrelated DOM substrings

### Requirement: Static HTML capability reports are dry-run and redacted
The system SHALL call `sectors-sina-html` and `sectors-xueqiu-html` only when a stored `eligible` capability report exists for the matching provider and revision, and SHALL refuse any runtime call otherwise. The capability promotion boundary delivered by `activate-fuyao-sector-fallback` is the **only** path to materialize such a report; this change MUST NOT introduce a second promotion path or a runtime store other than the one already wired. The probe subcommand SHALL default to dry-run, SHALL require `--allow-real` to issue any network request, SHALL write only an isolated SQLite/JSON store, SHALL refuse to run inside a production deployment profile unless explicit `MARKET_ENVIRONMENT_PROBE_ALLOW_REAL=1` and after-hours authorization are configured, SHALL include endpoints, host allowlist match, fixture coverage, field coverage, permission and challenge classification, and rate-limit outcomes, and SHALL redact any raw request or response body. Capability evidence SHALL NOT be promoted silently; promotion SHALL require the existing dry-run → `--apply` CLI boundary.

#### Scenario: Capability report is missing or non-eligible
- **WHEN** the runtime call lands and the matching stored report is missing or its status is not `eligible`
- **THEN** the adapter SHALL return an `AcquisitionFailure` of category `CONFIGURATION` with the matching `revision-mismatch` or `report-not-eligible` warning and SHALL perform zero network I/O

#### Scenario: Probe runs without `--allow-real`
- **WHEN** the operator runs `python -m src.market_environment.cli sectors probe --source sina-html` without `--allow-real`
- **THEN** the subcommand SHALL refuse to issue any HTTP request and SHALL exit with a structured dry-run report only

#### Scenario: Probe runs with `--allow-real` after-hours
- **WHEN** the operator runs `python -m src.market_environment.cli sectors probe --source sina-html --allow-real` inside an isolated after-hours profile with `MARKET_ENVIRONMENT_PROBE_ALLOW_REAL=1`
- **THEN** the subcommand SHALL fetch exactly one bodyless GET per source through the Scrapling engine, SHALL validate DOM coverage against the offline fixtures, SHALL write only to the isolated store, SHALL produce a redacted JSON report, and SHALL exit without writing a formal `sectors_snapshot` row

## Context

The existing sectors acquisition plan already owns Eastmoney primary/delayed requests,
capability-gated Fuyao fallback, dataapi enrichment, and provider shadow behavior. The shared
transport already supports JSON bodies, host policy, body digests, authentication-scope digests,
single-flight, and bounded retries, but its response evidence redaction must learn to inspect
JSON request bodies. The current Tushare token has not been granted the required THS API
permissions, so this design delivers an inert, testable integration and an `ineligible` probe
path rather than production activation.

## Goals / Non-Goals

**Goals:**

- Add an official Tushare THS exact-date fallback behind a matching capability report.
- Preserve a deterministic four-source order, provider authority, null semantics, and stable ranking.
- Keep authenticated POSTs inside the existing transport policy with no credential leakage.
- Provide fixture and explicitly authorized real-probe paths while defaulting all runtime switches off.

**Non-Goals:**

- No Tushare SDK, web scraping, Scrapling, Scrapy, Playwright, Selenium, challenge bypass, or TDX-derived sector source.
- No public API or snapshot schema change, automatic production activation, schedule enablement, or historical backfill.
- No second capability-promotion implementation; reuse the generic command from `activate-fuyao-sector-fallback`.

## Decisions

### 1. Use one official client behind the shared transport gateway

The adapter uses `https://api.tushare.pro` with canonical JSON POST payloads for
`ths_index`, `ths_daily`, and `moneyflow_ind_ths`. Each request carries source id
`sectors-tushare-ths`, the requested date, an authentication scope derived from the token, and
`cache_seconds=0`. The gateway remains responsible for pacing, retry, cooldown, and
single-flight. The client parses only bounded `code`, `msg`, `data.fields`, and `data.items`
values; it never places a complete response or request body in an exception.

The transport redactor recursively inspects JSON keys and replaces credential values in both
request diagnostics and provider error echoes. Request identity stores only body and
authentication-scope digests, so different accounts cannot share an identity while tokens stay
absent from keys, provenance, and reports.

### 2. Normalize one Tushare source adapter

The adapter first obtains the documented industry identities, then exact-date daily rows, then
same-date money-flow rows. All pages must be consumed and identity sets must remain unique and
consistent. Daily rows provide the minimum ranking candidate; optional flow/leader omissions
degrade field availability but never invent unsupported values. Rows are sorted by
`pct_change DESC, ts_code ASC`, then assigned the existing stable ranks and top-N shape.

### 3. Gate before any network I/O

`MARKET_ENVIRONMENT_TUSHARE_SECTORS_ENABLED` defaults to false. When enabled, the plan also
requires a token, an approved revision, and a PostgreSQL `eligible` report for
`tushare/sectors` with the exact revision. A failed gate records a bounded warning and directly
checks Fuyao; it does not instantiate or call the Tushare client.

### 4. Treat unit and leader semantics as probe-proven contract

`pct_change` maps to `changePct`. `net_amount` maps to yuan only after the capability fixture
and authorized probe prove its documented ten-thousand-yuan unit. A leader name is mapped only
when an official field and semantic validation prove it is a name; otherwise `leader` remains
null. `amount`, `mainNetPct`, `upCount`, and `downCount` remain null in every case.

### 5. Probe before rollout

Offline fixtures cover pagination, exact dates, duplicates, missing rows, units, ordering,
permissions, and token/error echo redaction. A real probe requires `--allow-real`, an explicit
date after settlement, and Secret-provided token; it writes only an isolated store and redacted
JSON. Any missing permission or unproven field contract yields `ineligible`. Only a later
reviewed report can be promoted by the generic capability command.

### 6. Keep deployment inert by default

Helm values add a Tushare existing Secret/key reference, `enabled=false`, and an empty approved
revision. Deployment env uses `secretKeyRef` without rendering the token. Schedules remain
disabled/suspended, Scrapling and Eastmoney enrichment remain off, and rollback only disables
the Tushare sectors switch.

## Risks / Trade-offs

- [Tushare permissions or field units change] -> Reject the capability report and require a new revision; never silently reinterpret values.
- [Tushare flow coverage is partial] -> Preserve valid daily ranking, set missing optional fields to null, and surface degraded warnings.
- [Authenticated POST errors echo secrets] -> Redact nested JSON credentials and bounded response evidence before persistence or display.
- [A disabled or unapproved source is accidentally called] -> Evaluate the capability gate before client construction and test zero-I/O routing.

## Migration Plan

1. Update specs, active plan, architecture, runbook, product spec, and status before code.
2. Implement transport redaction, Tushare config/client/probe, adapter, routing, and default-off Helm values with deterministic fixtures.
3. Run all offline gates; keep current token and runtime switch disabled while permissions are incomplete.
4. Only after explicit authorization and an eligible report, promote evidence, deploy the Secret reference and revision, and collect one current-date sectors dataset.
5. Roll back by disabling Tushare sectors only; retain reports, tasks, snapshots, and PVCs.

## Open Questions

None. Current missing permissions are represented as an `ineligible` report and do not block the offline implementation.

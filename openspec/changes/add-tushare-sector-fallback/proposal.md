## Why

The two Eastmoney sector endpoints share one provider failure domain, while the existing Fuyao fallback intentionally supplies only four reliable fields. Tushare Pro can provide an independent exact-date THS industry source, but the current account has not demonstrated permission for all required APIs, so the integration must remain disabled and capability-gated until authorized evidence is available.

## What Changes

- Add a `sectors-tushare-ths` source adapter that sends official JSON POST requests through the shared transport gateway for `ths_index`, `ths_daily`, and `moneyflow_ind_ths`.
- Fix the sector fallback order as `Eastmoney push2 -> Eastmoney push2delay -> Tushare THS -> Fuyao THS`, with zero provider I/O when an independent-provider capability gate is unsatisfied.
- Join catalog, daily, and money-flow responses by unique industry identity and require `trade_date` to prove the requested exact date.
- Map only verified Tushare fields: code, name, change percentage, main net flow, and leader. Keep amount, main net percentage, advancing count, and declining count `null`; never substitute company count, volume, or another semantically different value.
- Add default-off Tushare sectors configuration, approved revision `tushare-ths-sectors-v1`, Secret reference, deterministic probe fixtures, and an explicitly authorized after-hours real-probe path. Runtime requests require a matching promoted `eligible` capability report.
- Extend the shared transport redaction contract so credentials in authenticated JSON request bodies cannot enter request identities, diagnostics, response evidence, provenance, or capability reports, even when echoed by the provider.
- Keep the HTTP API, `SectorRow`, PostgreSQL snapshot schema, provider-free GET/status behavior, schedules, Eastmoney enrichment, Scrapling, and Fuyao defaults unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `sector-data-collection-stability`: Add a capability-gated Tushare THS independent fallback, fixed source order, exact `trade_date`, and explicit field-authority/null behavior.
- `provider-http-transport`: Add authenticated JSON POST isolation, request-body credential redaction, and no-TTL-cache-by-default behavior.

## Impact

- Affects market-environment provider configuration/client/probe code, the sectors source adapter and acquisition plan, shared transport diagnostics, composition wiring, Helm values/manifests, deterministic tests, and product/architecture/runbook/status documentation.
- Reuses the generic capability promotion boundary delivered by `activate-fuyao-sector-fallback`; this change must not implement a second promotion path or bypass that prerequisite.
- Adds no public HTTP route, database migration, frontend field, Tushare SDK, browser crawler, or automatic production activation.
- Real probe, report promotion, Secret/Helm rollout, and production collection remain separately authorized operations. With current permissions, Tushare stays disabled and any real report remains `ineligible`.

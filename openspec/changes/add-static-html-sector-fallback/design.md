## Context

This change extends the sectors fallback chain only — `Why` and the requirements are in `proposal.md` and `specs/sector-data-collection-stability/spec.md`. The chain today ends at Fuyao THS. There is already a Scrapling static engine profile and a capability-promotion boundary that ships redacted probe reports; both are the foundation this design reuses.

Two API hosts (Sina, Xueqiu) expose an industry card page that is text-only and renders without login. The card contains `name`, `changePct`, `amount`, and often a `leader` label. The four `SUPPLEMENTAL_FIELDS` (`mainNet`, `mainNetPct`, `upCount`, `downCount`) are not part of that card. Promoting any page-side numeric into those fields is forbidden by `sector-data-collection-stability`.

## Goals / Non-Goals

**Goals:**
- Ship two independent last-tier adapters behind the existing Scrapling engine and capability-gate machinery.
- Keep field authority strict (web-visible only) and prove it with offline fixtures and unit tests.
- Document the new chain position, settings/Helm gates, and remaining gaps without introducing a real probe or production activation.

**Non-Goals:**
- Filling `mainNet` / `mainNetPct` / `upCount` / `downCount` (those stay `null + warning`).
- Any real probe, capability report promotion, Helm rollout, or production data collection.
- Modifying `SectorRow`, the public HTTP API, the frontend, or the PostgreSQL schema.

## Decisions

### Two adapters, one shared scaffolding
- `sectors-sina-html` and `sectors-xueqiu-html` are independent `SourceAdapter` classes under `infrastructure/providers/sina_html/` and `xueqiu_html/`.
- A small shared module `infrastructure/providers/html_common/` carries the DOM-extraction helpers, fixture tolerance check, and DriftDetector used by both adapters, so the forbid-promotion-to-supplementary-fields rule is enforced in one place and unit-tested once.
- **Alternative considered:** make the two adapters share an abstract base class. Rejected because the two hosts have different DOM selectors, different leader-text conventions, and different prose; a base class would force a common abstraction that does not match either host.

### Scrapling-only transport, allowlist-enforced
- The two adapters accept requests only when the existing `ScraplingStaticEngineConfig` allowlist contains the exact `(host, source_id)` pair. Outside the allowlist, the adapter returns a `CONFIGURATION` `AcquisitionFailure` without touching the network layer.
- The adapter calls the engine through the existing `provider_http` gateway, never directly via `requests`. This is the same gate that already enforces host/single-flight/cooldown policy and redacts credentials in provenance.
- **Alternative considered:** let the adapter use a separate transport. Rejected — the warehouse rule ("HTTP source must go through the composition-root gateway") would be violated and the engine-neutral contract would split.

### Settings, composition, and the disabled-by-default gate
- A new `crawlFallback` segment is added to `bootstrap/settings.py`. `enabled=false` is the default. When `enabled=false`, `bootstrap/container.py` skips BOTH the Scrapling engine registration for these two hosts AND the registration of the two adapters. Skipping at registration time guarantees zero I/O even if a code path somewhere else had a stale reference.
- The gate is **independent** of the existing `scrapling.enabled` segment but also defaults to `false`. Helm overlays set `marketEnvironment.crawlFallback.enabled=false` so the chart does not change runtime behavior until an operator explicitly opts in.

### Acquisition-plan placement
- The existing `sectors_acquisition.py` plan ends at Fuyao. After Fuyao, the plan appends `sina-html` then `xueqiu-html`. Each is conditional on the gate; failure short-circuits to the next. None of them short-circuit Fuyao or any higher tier.
- The HTML tier is **never** wired into the Eastmoney enrichment path. The two paths are conceptually distinct: enrichment fills `mainNet` / `upCount` / `downCount` for a row that already has `name` / `changePct` from the Eastmoney pair; the HTML tier substitutes `name` / `changePct` / `amount` / `leader` when the Eastmoney pair itself is unavailable.

### Capability-gate reuses `activate-fuyao-sector-fallback` machinery
- The capability promotion path is the same CLI delivered by `activate-fuyao-sector-fallback`. No second path is added.
- Capability revisions `crawl-html-sina-v1` and `crawl-html-xueqiu-v1` are the only strings expected by the runtime. The provider_capability_policy table currently keys on `(provider, dataset, revision)`; both new sources register there at startup and are matched against the gate before I/O.

### Offline fixtures and tests
- Synthetic HTML fixtures live under `tests/fixtures/sina_html/` and `tests/fixtures/xueqiu_html/`. They are hand-authored and NEVER pulled from the live site during CI or commit.
- Tests cover: happy path, selector drift, 401, 403, login wall, upstream short-circuit (zero I/O at the network layer when a higher tier succeeds), supplementary-field null authority, capability-gate (disabled / missing / non-eligible / revision mismatch), exact-date evidence, Helm render.

### Drift tolerance
- Each adapter ships with a per-fixture "selector footprint" object: a small set of selectors and the expected substring or regex. The DriftDetector compares the actual page output to the expected footprint; on any mismatch, the adapter emits `dom-drift`, classifies the row quality as `fallback` or `degraded`, and refrains from writing a name/changePct/amount/leader string fabricated from unrelated DOM substrings.

## Risks / Trade-offs

- **[Risk] DOM drift is a routine event on Sina/Xueqiu.** → Mitigation: every adapter ships with a DriftDetector and degrades quality rather than fabricating rows. Fixtures must be re-captured by an authorized operator after-hours when production drift is observed.
- **[Risk] Xueqiu presents a login wall more frequently than Sina.** → Mitigation: the engine returns 401/403/challenge classification; the adapter maps these to non-retryable permission failures with a `host-challenge-detected` warning and proceeds to the next tier. The dashboard shows Xueqiu as `degraded` whenever it fails; this is acceptable for a last-tier fallback.
- **[Risk] Operators turn the gate on by accident.** → Mitigation: settings default to `enabled=false`; Helm sets `crawlFallback.enabled=false`. The probe CLI requires `--allow-real` plus `MARKET_ENVIRONMENT_PROBE_ALLOW_REAL=1`. There is no scheduled cron for the HTML tier; `scheduledCollection` stays `false`/`true` (suspended).
- **[Risk] Real fixtures accidentally committed.** → Mitigation: fixtures are synthetic and committed in a separately named `tests/fixtures/sina_html/` and `tests/fixtures/xueqiu_html/` directory; the same `tests/fixtures/*` directory tree that already houses offline fixtures for the existing chain. Lint rule forbids committing any HTML that begins with `<!DOCTYPE html><html>` plus a real `og:` title etc., enforced manually by code review.
- **[Risk] Leader-name string occasionally contains stray HTML entities.** → Mitigation: the adapter applies the same `name` normalization used by the Eastmoney adapter (decode entities, collapse whitespace, trim) and unit-tests cases for `&amp;` and `&nbsp;`.

## Migration Plan

- No database migration required.
- No image rollout required for the default-disabled configuration.
- Rollback: set `marketEnvironment.crawlFallback.enabled=false` in the Helm values overlay and roll a complete release; the rollout path uses the same `image` as the baseline and reattaches the default chart. No PVC, capability report, or snapshot is deleted; only the gate flips.
- Archive the change only after every task (including the docs-sync and verify tasks) is complete and `python scripts/check-docs-contract.py --mode=fast` and `python -m pytest tests -q` pass.

## Open Questions

- None. The four assumption defaults (Tushare decoupled, Scrapling scope limited, fixtures offline-only, Xueqiu login tolerance strict) are recorded in `proposal.md` and the spec delta. The remaining unknowns (operator-managed capture of real fixtures, real `--allow-real` probe, capability-report promotion, image rollout, single-dataset production collection) are explicitly out-of-scope and are listed as `Remaining Gaps` in the active exec plan.

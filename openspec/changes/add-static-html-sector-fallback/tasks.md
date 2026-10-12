## 1. Adapter scaffolding and shared HTML helpers

- [x] 1.1 Create `src/market_environment/infrastructure/providers/html_common/` with `drift.py`, `selectors.py`, and `fixture_loader.py`; unit-test DriftDetector behaviour on a synthetic footprint (happy/drift) and verify fixture_loader returns the synthetic HTML verbatim without raising
- [x] 1.2 Create `src/market_environment/infrastructure/providers/sina_html/` with `adapter.py`, `mapping.py`, and `__init__.py`; verify `SinaHtmlSectorAdapter` exports a typed `SourceAdapter` shape compatible with `SourceAdapterRegistry.register` and an `id == "sectors-sina-html"`
- [x] 1.3 Create `src/market_environment/infrastructure/providers/xueqiu_html/` with the equivalent structure and `id == "sectors-xueqiu-html"`; verify both adapters import without registering side effects and respect the same `AcquisitionFailure` shape used by the existing Fuyao adapter

## 2. SectorRow mapping and strict field authority

- [x] 2.1 Implement `SinaHtmlSectorAdapter._to_sector_row` and verify that with the captured fixture the row returns `code`, `name`, `changePct`, `amount`, `leader` (text) and leaves `mainNet`, `mainNetPct`, `upCount`, `downCount` as `null`, each with a structured warning
- [x] 2.2 Implement the equivalent for Xueqiu and verify a synthetic fixture where the page exposes a numeric badge labelled `inflow` still leaves `mainNet` and friends as `null`
- [x] 2.3 Add a unit test that wraps a synthetic fixture carrying a leader identifier (numeric/code) and verify the row's `leader` field is `null` with a `leader-identifier-not-name` warning; verify the same rule when only a numeric badge could be misinterpreted as a leader
- [x] 2.4 Add a unit test that wraps a synthetic fixture containing `&amp;` / `&nbsp;` and verify `name` and `leader` are correctly normalized (entity decoding + whitespace collapse)

## 3. Transport-bound and capability-gated adapter

- [x] 3.1 Implement `SinaHtmlSectorAdapter.fetch` to call the Scrapling engine via the `provider_http` gateway, with the request's `host` and `source_id` allowlist check; verify `enabled=false` or missing/non-eligible/mismatched report yields `CONFIGURATION` failure with zero engine I/O and zero `requests` I/O (assert via a transport spy)
- [x] 3.2 Implement the 401/403/login-wall/CAPTCHA classification path; verify the adapter returns a classified non-retryable failure, emits `host-permission-denied` or `host-challenge-detected` warning, and never retries or silently falls back
- [x] 3.3 Implement the DOM-drift detection path; verify drift emits a `dom-drift` warning, marks the row as `fallback`/`degraded` quality, and never fabricates a `name`/`changePct`/`amount`/`leader` from unrelated substrings
- [x] 3.4 Mirror 3.1–3.3 for Xueqiu and verify identical behaviour under fixture injection

## 4. Acquisition plan integration and short-circuit

- [x] 4.1 Extend `src/market_environment/infrastructure/providers/sectors_acquisition.py` with `EASTMONEY_SECTOR_HTML_SINA_SOURCE_ID` and `EASTMONEY_SECTOR_HTML_XUEQIU_SOURCE_ID` constants and registry wiring; verify the acquisition order in any enabled listing ends at Fuyao before HTML sources
- [x] 4.2 Wire the chain so any higher-tier success short-circuits the HTML tier; verify with a transport spy that a successful Eastmoney delayed response produces zero HTML-source requests
- [x] 4.3 Wire the capability gate so missing/non-eligible/mismatched report disables just that HTML source without affecting the rest of the chain; verify with two independent gates that toggling one does not toggle the other
- [x] 4.4 Wire the all-source-failure path so the existing `failed-retained` and `failed-missing` semantics from the higher tier remain authoritative; verify no HTML-tier failure path writes a formal snapshot row

## 5. Composition, settings, and Helm gates

- [x] 5.1 Add `CrawlFallbackConfig` to `bootstrap/settings.py`; verify `MARKET_ENVIRONMENT_CRAWL_FALLBACK_ENABLED=0` (the default) leaves `enabled=False` and the resulting config is not exposed through any env
- [x] 5.2 Update `bootstrap/container.py` so `enabled=False` skips registration of both the Scrapling engine (for the two hosts) AND both HTML adapters; verify a focused test loads a baseline container and asserts the registry reports the two source IDs as absent
- [x] 5.3 Add `marketEnvironment.crawlFallback` block to `deploy/helm/a-stock/values.yaml` with `enabled=false` and `sources=["sina","xueqiu"]`; verify `helm template` does not change baseline output when the block is left at its default
- [x] 5.4 Add a Helm overlay fixture test that flips `crawlFallback.enabled=true` and verifies the rendered manifest includes exactly the two new source ids and does NOT include any token, cookie, or secret field
- [x] 5.5 Verify `scheduledCollection` remains `enabled=false` and `suspend=true` regardless of `crawlFallback.enabled`

## 6. Offline fixtures and adapter tests

- [x] 6.1 Add `tests/fixtures/sina_html/cards.json` plus a single synthetic `page.html` and `expected_rows.json`; verify the captured footprint matches DriftDetector's happy-path comparison
- [x] 6.2 Add `tests/fixtures/xueqiu_html/cards.json` plus `page.html` and `expected_rows.json`; verify the equivalent happy-path comparison
- [x] 6.3 Add fixture for the "DOM drifts, page still 200" case (renamed selector inside the card body); verify DriftDetector emits drift and the adapter classifies fallback/degraded without fabricating rows
- [x] 6.4 Add fixture for the "login wall 401" case; verify the engine spy receives the 401, the adapter returns a non-retryable permission failure, and no network I/O follows
- [x] 6.5 Add fixture for the "leader identifier exposed as numeric" case; verify the row's `leader` field is `null` with the expected warning

## 7. Capability probe CLI

- [x] 7.1 Add `python -m src.market_environment.cli sectors probe --source {sina-html|xueqiu-html}` subcommand in dry-run mode; verify invoking without `--allow-real` performs zero network I/O and prints a structured dry-run report
- [x] 7.2 Add `--allow-real` plus `MARKET_ENVIRONMENT_PROBE_ALLOW_REAL=1`; verify the subcommand issues exactly one bodyless GET per source through the Scrapling engine and writes only an isolated store, never a formal `sectors_snapshot` row
- [x] 7.3 Add a `redact` step that strips raw bodies and credentials from the report; verify the test asserts no raw request/response body, no token, no cookie is present in the written JSON
- [x] 7.4 Wire the subcommand into the existing capability-promotion boundary from `activate-fuyao-sector-fallback`; verify no second promotion path is added and the existing promotion CLI still works

## 8. Documentation and active plan

- [x] 8.1 Add an active exec plan under `docs/exec-plans/active/` named after this change; populate `Stage`, `Status`, `Acceptance`, `Completion Evidence`, `Remaining Gaps`, `Next Step`; verify `python scripts/check-docs-contract.py --mode=fast` is satisfied
- [x] 8.2 Add the two new sources to the data-sources table in `docs/architecture.md`; add an `infrastructure` paragraph describing the two adapters and the gate
- [x] 8.3 Add a "末层 HTML 静态源" section to `docs/runbooks.md` immediately after the existing "统一 acquisition adapter 与可选 Scrapling 排错" section; explicitly forbid challenge solving, SPA rendering, and login bypass
- [x] 8.4 If `docs/product-specs/` exists, add a "Crawl 末层" subsection describing the field authority and null discipline; if it does not, skip the section and record that as a `Remaining Gap`
- [x] 8.5 Run `python scripts/check-docs-contract.py --mode=fast` and verify it passes with the new documentation

## 9. Verification and submit

- [x] 9.1 Run `python -m pytest tests -q` and record the result; verify no warnings about deprecated fixtures and no skipped HTML-tier tests beyond the explicit "awaits authorized fixture capture" markers
- [x] 9.2 Run `python scripts/check-docs-contract.py --mode=full` and record the result; ensure all docs references resolve
- [x] 9.3 Run focused adapter/transport/Helm/security tests and record their results; verify the forbid-promotion-to-supplementary-fields rule is exercised by at least one synthetic fixture per host
- [x] 9.4 Mark this change as ready for archive once every prior task is checked; record a final `Remaining Gaps` (authorized real probe, capability report promotion, image rollout, single-dataset production collection) that operators must own

## 1. Plan And Documentation Contract

- [x] 1.1 Create `docs/exec-plans/active/schedule-after-market-data-collection.md` with all required plan fields and add it to the active plan index before changing code.
- [x] 1.2 Update the market-environment product specification for automatic five-dataset after-market collection, partial-result visibility, manual recovery, and the explicit holiday limitation.
- [x] 1.3 Update `docs/architecture.md` for the CronJob-to-CLI-to-coordinator flow, shared PVC/SQLite boundary, concurrency protection, and separation from the trading-rules GitHub Actions workflow.
- [x] 1.4 Update `docs/runbooks.md` with enable, disable, suspend, one-off Job, log inspection, partial recovery, timeout, holiday, and rollback procedures for Kustomize and Helm.
- [x] 1.5 Update `docs/status.md` and the TrueNAS/k3s deployment documentation or plan where the new scheduled resource changes the documented deployment workflow.

## 2. Scheduled Collection CLI

- [x] 2.1 Add a kebab-case `snapshots scheduled-refresh` CLI subcommand that resolves the current date and time in `Asia/Shanghai` without shell date interpolation.
- [x] 2.2 Implement weekend `skipped` handling and settlement-boundary rejection before any provider call, reusing the configured `MARKET_ENVIRONMENT_SETTLEMENT_TIME` semantics.
- [x] 2.3 Route valid scheduled runs through `CollectionCoordinator.collect()` with the default datasets `core`, `breadth`, `limits`, `sectors`, and `activeDirection`, while preserving optional explicit dataset selection for diagnostics.
- [x] 2.4 Emit one structured JSON result containing trigger, run ID, date, parent status, and per-task source, observations, duration, status, and warning.
- [x] 2.5 Return code 0 for `success` and weekend `skipped`, and a documented nonzero code for `partial`, `failed`, pre-settlement rejection, or invalid configuration without discarding committed task results.
- [x] 2.6 Keep the existing `snapshots refresh --as-of` behavior and output backward compatible.

## 3. CLI And Coordinator Verification

- [x] 3.1 Add deterministic CLI tests for Shanghai timezone resolution, the default five-dataset selection, weekend skip, pre-settlement rejection, and structured output fields.
- [x] 3.2 Add scheduled-run tests for success, one-dataset partial failure, all-dataset failure, and exact-date retained/missing behavior using fixture providers and temporary SQLite storage.
- [x] 3.3 Add an overlap test proving a scheduled trigger and manual trigger for the same dataset/date reuse or report the active lease without duplicate provider calls.
- [x] 3.4 Add a regression test proving normal dashboard GET requests remain provider-free and responsive while a scheduled collection task is active.

## 4. Kustomize CronJob

- [x] 4.1 Add a lower-case kebab-case `deploy/k3s/market-data-collection-cronjob.yaml` resource and register it in `deploy/k3s/kustomization.yaml`.
- [x] 4.2 Configure the CronJob for `Asia/Shanghai`, default schedule `30 16 * * 1-5`, `concurrencyPolicy: Forbid`, `backoffLimit: 0`, starting/active deadlines, bounded Job history, and the scheduled-refresh command.
- [x] 4.3 Reuse the dashboard image, snapshot path, PVC, timezone/provider environment, non-root security context, read-only root filesystem, dropped capabilities, disabled service-account token, `/tmp` volume, and bounded resources.
- [x] 4.4 Verify `kubectl kustomize deploy/k3s` renders one valid CronJob that targets the same image and PVC as the Deployment.

## 5. Helm CronJob

- [x] 5.1 Add `marketEnvironment.scheduledCollection` values for enabled, suspend, schedule, timeZone, starting deadline, active deadline, Job history, resources, and optional Pod scheduling overrides with documented defaults.
- [x] 5.2 Add a conditional lower-case kebab-case Helm CronJob template that matches the Kustomize command, shared PVC, environment, security, concurrency, timeout, and retry semantics.
- [x] 5.3 Add or update Helm rendering tests to prove the default CronJob is enabled, disabled mode omits it, suspended mode retains it, and custom schedule/timezone values render correctly.
- [x] 5.4 Run `helm lint deploy/helm/a-stock` and render enabled, disabled, and suspended configurations with `helm template`.

## 6. End-To-End Acceptance

- [x] 6.1 Run focused and full Python tests, Kustomize rendering, Helm lint/template, and `git diff --check`.
- [x] 6.2 Run a local fixture-backed scheduled-refresh smoke and confirm `/data-collection` reads the persisted run/task states without provider calls.
- [x] 6.3 Verify a fixture partial run preserves successful sibling snapshots, reports the failed row for targeted retry, and does not automatically start a second full batch.
- [x] 6.4 Run `openspec validate schedule-after-market-data-collection --strict` and the full docs-contract gate.
- [x] 6.5 Update the active plan `Status`, `Completion Evidence`, `Remaining Gaps`, and `Next Step` with exact command results and the unresolved exchange-holiday limitation.

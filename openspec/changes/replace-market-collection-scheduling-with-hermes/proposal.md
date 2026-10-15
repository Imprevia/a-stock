## Why

The project-owned Kubernetes CronJob duplicates scheduling concerns that can be owned by the already-running Hermes Agent, while the current HTTP API requires a caller to coordinate an asynchronous start-and-poll flow and does not expose stable failure classification for every dataset. Moving the schedule outside the application and adding one sync-first, idempotent full-collection endpoint gives the operator one observable trigger path without losing the existing exact-date, failure-isolation, and retained-data guarantees.

## What Changes

- **BREAKING** Retire repository-managed automatic market-data scheduling: Helm/Kustomize shall no longer render or activate a market-data CronJob, and the scheduling overlays and activation workflow shall be removed after any live CronJob has been stopped through the reviewed rollback path. Scheduling/provider collection Jobs remain absent. The only temporary Kubernetes Job permitted during an authorized backend/schema rollout is the exact provider-free `a-stock-schema-migration` Helm hook; it runs `alembic upgrade head` once, is absent after success, and never authorizes a collection or provider call. Explicit coordinator and maintenance CLI entry points remain available; ordinary reads remain provider-free.
- Add a dedicated full-collection HTTP endpoint that always targets all seven public daily datasets, derives the effective date in `Asia/Shanghai`, rejects pre-settlement execution, and waits for the persisted run to reach a terminal state up to a bounded timeout.
- Return HTTP 200 with the complete terminal run when it finishes within the wait budget; otherwise return HTTP 202 with the same `runId` and a status URL while the run continues independently of the client connection.
- Require an `Idempotency-Key` for the full-collection endpoint. The same key and request fingerprint reuse one persisted run; reusing a key with a different request is rejected with HTTP 409.
- Expose redaction-safe structured failure information for every dataset (`category`, `message`, `retryable`, and retained state) while preserving `success`, `partial`, `failed-retained`, `failed-missing`, `blocked`, and `busy` distinctions.
- Add a dedicated automation-write enable switch. Per the operator's explicit network decision, the endpoint uses no application credential on the trusted, non-public internal network; documentation must state that every client able to route to `192.168.1.20:32001` can invoke the enabled endpoint and that idempotency is not authentication.
- Configure Hermes Agent on `192.168.1.21` to run at 16:30 on weekdays in `Asia/Shanghai`, call `http://192.168.1.20:32001`, follow a 202 response without issuing another POST, and deliver a concise Chinese per-dataset outcome. The caller shall not perform catch-up later than the existing 30-minute scheduling deadline.
- Reconcile the superseded Kubernetes natural-trigger acceptance work in the active THS plan, and document independent rollback: disable the Hermes job or the automation-write switch without deleting PostgreSQL history or successful snapshots.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-data-collection-management`: Add the sync-first idempotent seven-dataset automation endpoint, structured failure contract, bounded wait behavior, and explicitly accepted trusted-LAN access boundary.
- `after-market-data-collection-scheduling`: Replace the deployable Kubernetes CronJob contract with an external Hermes schedule and remove project-owned automatic scheduling resources while preserving date, overlap, persistence, and observability guarantees.

## Impact

- Backend HTTP schemas/router, application collection ports, coordinator adapters, PostgreSQL run/task persistence, idempotency storage, and migrations.
- Helm/Kustomize scheduling templates, values/schema/overlays, TrueNAS scheduling commands and validators, render/deployment tests, the legacy `scheduled-refresh` deployment path, and the componentized deployment flow that must run the schema hook only in the database phase and use `--no-hooks` for final full-release convergence.
- Hermes runtime configuration and cron job on `192.168.1.21`, including top-level `Asia/Shanghai` timezone, bounded script and Agent-inactivity timeouts, deterministic caller/prompt, delivery target, and gateway health checks.
- Architecture, product specification, repository guide, runbook, status, active execution plans, OpenSpec main specs after archive, and focused/full/docs-contract verification.
- Production rollout requires a separate explicit authorization because stopping a live CronJob, deploying the endpoint, enabling automation writes, and creating a Hermes cron job are external writes; this proposal performs none of them.

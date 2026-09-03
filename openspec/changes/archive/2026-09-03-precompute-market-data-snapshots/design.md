## Context

See `proposal.md` for motivation. The current service keeps core and Chapter 01 results in process memory for 30 seconds. Market breadth and active direction share a `stock` provider group, so breadth first attempts a nominal full-market response and active direction is unavailable when that response is capped. The exact breadth fallback takes multiple rate-limited requests, making synchronous cold loads unsuitable for a post-market research API.

The repository requires Python-first, cross-platform behavior, explicit provider quality, exact-date isolation, and no reuse of today's snapshot for historical requests. External Eastmoney calls must continue through the shared serial limiter.

## Goals / Non-Goals

**Goals:**

- Remove repeated market-wide collection from the normal API request path.
- Reuse successful results across process restarts and same-host API workers.
- Preserve exact trading-date and provider-quality semantics.
- Make the first-party refresh path observable, testable, and operable after market close.
- Keep current endpoint paths and existing response fields backward compatible.

**Non-Goals:**

- Introducing Redis or another required network service in the first implementation.
- Building an intraday tick store, historical backfill service, or general-purpose data lake.
- Weakening the global Eastmoney limiter or parallelizing calls in violation of its safety boundary.
- Treating cached data as validated trading-rule evidence without the existing snapshot and evidence workflow.

## Decisions

### 1. Use a SQLite snapshot store by default

The default store will be a SQLite database under `.artifacts/market-environment/`, configurable through an environment variable. SQLite is in the Python standard library, works on Windows/macOS/Linux, provides atomic commits and checksums, survives reloads, and can coordinate workers on one host.

The store will contain:

- snapshot entries keyed by `(dataset, as_of)` with canonical JSON payload, source, status, observations, warnings, fetched time, settlement confirmation, checksum, and schema version;
- refresh leases keyed by `(dataset, as_of)` with owner and bounded expiry;
- optional refresh-run records summarizing operator-triggered precomputation.

Alternative considered: JSON files per date. They are simple but make cross-worker leasing, atomic metadata updates, retention queries, and partial refresh reporting harder. Redis remains a future adapter if deployment becomes multi-host.

### 2. Persist normalized dataset inputs and derived API results

The cache boundary is the normalized dataset contract, not raw HTTP bodies. Breadth stores its exact counts, valid sample count, median return, source and warnings. Active direction stores the server-ranked Top-N normalized rows plus the derived top-30 clustering and top-10 display result. Each canonical payload receives a checksum before commit.

This keeps the store small and auditable while avoiding a false requirement to reconstruct a complete 5,000+ row response that the provider does not reliably return.

Alternative considered: persist every provider response. Raw responses increase storage and couple replay to unstable upstream formats without improving the current API evidence contract.

### 3. Split breadth and active-direction acquisition

`breadth` and `activeDirection` become separate refreshable datasets.

- Breadth directly uses the validated sorted-page algorithm and skips the known-incomplete nominal full-market request.
- Active direction requests a turnover-sorted Top-N page containing the fields required by the current top-30 cluster and top-10 presentation calculations.
- A `summary` request composes stored dataset results; it does not force them back into one acquisition group.

Alternative considered: retain one shared full-market snapshot. This is only efficient when a provider reliably returns all rows in one request, which is not true for the current source.

### 4. Apply trading-phase-aware freshness

Freshness is configured per dataset rather than through one service-wide TTL.

- During an unfinished current trading day, successful entries use a short soft TTL.
- After the configured settlement time, an explicitly refreshed successful entry is marked settled and remains reusable for that trading date.
- Historical requests only read an exact stored date. They never trigger current-snapshot providers or substitute today's data.
- Failed results may be retained for diagnostics but never replace a previous successful payload.

The API adds optional cache metadata to dataset quality: `cacheState`, `snapshotFetchedAt`, `refreshing`, and `refreshWarning`. Existing `status`, `warnings`, values, and null semantics remain authoritative.

### 5. Use stale-while-revalidate with SQLite leases

For a fresh hit, the service reads local data and returns immediately. For a stale hit, it returns the last successful payload and attempts a background refresh only after acquiring the `(dataset, as_of)` lease. Other workers observe the lease and continue serving stale data.

For a cold miss, the request that acquires the lease performs the existing synchronous refresh for compatibility; concurrent requests wait for a bounded interval and then read the committed result. Normal operation avoids this path through the after-market refresh command.

Leases have an expiry so crashes cannot block future refreshes. Writes use a transaction and only replace the successful snapshot after payload validation and checksum generation.

Alternative considered: process-local locks. They already prevent duplicate work within one service instance but do not cover reloads or multiple workers.

### 6. Provide one explicit refresh command

A Python module CLI will accept an exact `--as-of` date, selected datasets or all configured datasets, and `--force`. It will emit a structured summary suitable for runbooks and later scheduling. The first implementation adds the command and documents Windows/macOS/Linux invocation; it does not add an operating-system-specific scheduler.

The command validates that current-snapshot-only providers are used only for the intended market date and after the configured settlement boundary unless `--force` is explicitly supplied for local diagnostics.

### 7. Measure provider and cache phases separately

Refresh results and service logs will record cache lookup, lease wait, provider collection, derivation, validation, and store-write durations. Tests will assert provider call counts and warm-read behavior; wall-clock performance acceptance will run against fixtures/local storage so external network variance does not make the gate flaky.

## Risks / Trade-offs

- [SQLite on a shared network filesystem may have unreliable locking] -> Document that the default adapter supports one host and a local filesystem; require a future shared-store adapter for multi-host deployment.
- [Stale evidence may be mistaken for fresh evidence] -> Return explicit additive cache metadata and preserve provider warnings and exact snapshot timestamps.
- [A settlement-time refresh may capture incomplete upstream data] -> Keep observation and completeness validation, do not mark failed/partial data as settled success, and support a forced rerun.
- [Cold miss can still be slow] -> Make after-market precomputation the documented normal path and retain bounded single-flight behavior only as a compatibility fallback.
- [Top-N endpoint ordering or cap changes upstream] -> Validate ordering, minimum sample size, and required fields before replacing the previous successful snapshot.
- [Database schema evolves] -> Store a schema version and use forward-only, idempotent migrations with backup/rollback instructions.

## Migration Plan

1. Create the active exec plan and update architecture, product specification, and runbook before code changes.
2. Add the SQLite store behind a new interface while leaving the current memory cache behavior available as a fallback.
3. Add separated breadth and active-direction collectors and fixture-based validation.
4. Add the refresh command and generate a current-date snapshot in local verification.
5. Change Chapter 01 reads to prefer the persistent store, then enable stale-while-revalidate and leases.
6. Keep existing endpoint fields and validate old response models throughout rollout.
7. Roll back by disabling the persistent cache configuration and returning to the current provider path; the SQLite artifact can remain for diagnosis because it is outside version control.

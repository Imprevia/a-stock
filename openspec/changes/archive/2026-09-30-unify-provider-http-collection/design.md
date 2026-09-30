# Design

## Context

See `proposal.md` and the existing provider stability specifications. `EastmoneyClient`
already owns an Eastmoney limiter and urllib3 retry adapter, while several market
provider paths and the TDX package client call `requests.Session.get` directly.

## Goals / Non-Goals

**Goals:**

- Centralize transport behavior without changing provider routing or response contracts.
- Prevent duplicate in-flight calls and repeated short-window live requests.
- Keep UA selection stable per host session and observable in deterministic tests.
- Bound repeated host failures so existing fallbacks can take over quickly.

**Non-Goals:**

- Proxy rotation, cookie injection, TLS/browser fingerprint emulation, or bypassing access controls.
- Cross-date data substitution or changing the existing provider capability gates.
- Introducing a new runtime dependency.

## Decisions

### Shared transport boundary

Add a dependency-light transport module under `src/trading_system/data/` that owns
host policies, sessions, UA selection, single-flight state, TTL entries, and circuit
state. `EastmoneyClient` remains the compatibility facade for its existing failure
types and uses the same host policy rather than creating a second limiter.

### Host policy and failure classification

Use per-host policies with a minimum interval, jitter, connect/read timeout, retry
budget, request budget, failure threshold, and cooldown. Retry only transport errors,
408, 429, and 5xx. Permission, other 4xx, and response-contract failures fail fast.
`Retry-After` is used only when bounded and parseable; otherwise exponential backoff
with jitter is used.

### Stable UA and headers

Use a small modern browser UA pool with injectable selection. A host session selects
one UA and standard `Accept`, `Accept-Language`, and `Accept-Encoding` headers. A new
session may rotate the UA; individual requests do not.

### Cache and single-flight

Cache only successful GET responses. Live quote/ranking requests use a short TTL,
while historical/package keys include the requested date. Failed, malformed, and
permission responses are never cached as successful data. In-flight identical calls
share one future/result.

### Provider integration

Migrate direct Tencent, Baidu, Sina, TDX, and name-enrichment calls first. Preserve
Fuyao's API-key-specific request and error handling, but make its transport gate and
session policy compatible with the shared primitives. Preserve all existing fallback
ordering and quality metadata.

## Risks / Trade-offs

- [Risk] A short TTL can serve slightly older intraday data. -> Keep the TTL limited to
  request-layer live calls and retain explicit force-refresh paths.
- [Risk] A circuit may hide a host recovery if cooldown is too long. -> Use bounded
  cooldowns and one half-open probe; expose state in diagnostics.
- [Risk] Wrapping existing retry adapters can double-retry. -> Remove nested retry
  behavior from migrated paths and keep one authoritative retry budget per host.
- [Risk] UA rotation can make tests nondeterministic. -> Inject RNG/selector and use a
  fixed fixture pool in tests.

## Migration Plan

1. Add the transport primitives and focused unit tests without changing provider callers.
2. Migrate direct provider requests and adapt Eastmoney compatibility behavior.
3. Run focused provider/collection tests, then full Python tests and docs gates.
4. Observe authorized after-hours smoke metrics before enabling any new production path.
5. Roll back by restoring provider adapters to the compatibility facade; durable snapshots
   and feature flags require no schema migration.

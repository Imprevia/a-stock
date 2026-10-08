## Context

See `proposal.md` for motivation and the delta specs for the behavioral contract. The backend now has a composition root, provider-free application queries, five dataset collectors, typed `DatasetDate`/`CollectionCandidate`/`CollectionOutcome` values, PostgreSQL leases and failure retention, and a shared synchronous HTTP client with host pacing, bounded retries, single-flight, short cache, and cooldown.

The main acquisition path still crosses incompatible seams:

- the application collector port declares `collect(DatasetDate) -> CollectionOutcome`, while the coordinator reflects over collector-specific `collect_task(task, started, lease, ...)` methods returning persistence task records;
- runtime composition injects a subclass of the legacy all-dataset `MarketDataProvider` into every collector;
- collectors understand vendor order, Fuyao gates, Eastmoney fallback/enrichment, TDX derivation, shadow comparison, provider quality dictionaries, and storage details;
- provider clients return `ProviderResult`, arbitrary dictionaries, Fuyao-specific results, TDX packages, normalized limits detail, or exceptions rather than one acquisition contract;
- the shared HTTP policy is tied to `requests.Response`, while Fuyao retains API-key-specific sessions and gates that must be migrated without weakening its business-error semantics;
- Scrapling is not installed. Its static fetcher can improve compatibility for an authorized host with HTTP/TLS fingerprint sensitivity, but its spider, proxy, challenge-solving, and browser orchestration overlap or conflict with existing retry, lease, scheduling, and access-control rules.

The implementation must preserve the five dataset identifiers, exact-date semantics, provider ordering and feature flags, same-date retention, PostgreSQL fencing, formal/shadow separation, public API compatibility, provider-free reads, and the in-progress Fuyao sector enrichment contract.

## Goals / Non-Goals

**Goals:**

- Make the typed dataset collector outcome the only application-facing acquisition result.
- Isolate vendor parsing, authentication, date proof, field authority, and response validation in source adapters.
- Express each dataset's priority, fallback, shadow, enrichment, and capability gates as one deterministic acquisition plan.
- Keep one authoritative transport policy while allowing explicitly registered HTTP request engines.
- Introduce a default-disabled Scrapling static HTTP engine that can be verified against the default requests engine without changing provider semantics.
- Migrate incrementally with characterization tests and compatibility adapters so source, warning, checksum, retention, and API behavior stay attributable.

**Non-Goals:**

- Do not change market calculations, provider priority, feature-flag defaults, settlement boundaries, snapshot schema, API routes, or frontend behavior.
- Do not make every provider use HTTP: mootdx/TCP and TDX package parsing remain non-HTTP source adapters governed by the same acquisition result contract.
- Do not add Scrapling Spider, proxy rotation, CAPTCHA solving, stealth escalation after 401/403, JavaScript/browser fetching, remote CDP, or a browser worker in this change.
- Do not run real providers, write production snapshots, activate scheduling, deploy to Kubernetes, or change production configuration as part of implementation verification.
- Do not delete stable root imports or the legacy provider facade until all runtime and repository/external compatibility consumers are proven migrated.

## Decisions

### 1. Separate application collection, dataset acquisition, source adapters, and transport engines

The target dependency flow is:

```text
application command
  -> DatasetCollectorRegistry
  -> DatasetCollector.collect(DatasetDate)
  -> DatasetAcquisitionPlan
  -> SourceAdapterRegistry
  -> SourceAdapter.acquire(SourceRequest)
  -> governed transport or non-HTTP client
  -> normalized CollectionOutcome
  -> coordinator commit/retention/materialization
```

The application port owns only the stable dataset/date request and normalized outcome. Acquisition plans and source adapters are infrastructure because they contain provider routing and I/O. Transport engines sit below the shared policy gateway and cannot decide dataset fallback or evidence quality.

Alternative considered: expose one vendor client per provider directly to collectors. Rejected because a dataset may combine several vendors and supplemental steps, while provider clients do not model product-level source priority, field authority, or exact-date fallback rules.

### 2. Extend the existing typed values instead of introducing a second parallel model

`CollectionCandidate`, `QualityMetadata`, and `CollectionOutcome` remain the cross-layer foundation. They gain explicit acquisition evidence needed by the specs: provider/source revision, fetched time, actual date, field availability, ordered attempts, phase timings, evidence fingerprint, and redacted provenance. Payloads remain dataset-specific mappings initially so provider relocation is not combined with a full DTO rewrite.

Failures use a typed acquisition failure with a stable category such as configuration, engine-unavailable, network, rate-limit, permission, challenge, contract, date-mismatch, insufficient, or internal. Retryability is evidence for the acquisition plan; the coordinator never retries a provider or interprets vendor exceptions.

Alternative considered: retain `payload["quality"]` dictionaries as the integration contract. Rejected because spelling, dates, observations, warnings, and supported-field behavior currently vary by source and cannot be enforced at the boundary.

### 3. Dataset acquisition plans own policy; source adapters own mechanics and truth validation

Each stable dataset receives one plan:

- `core`: five independently evaluated index subplans, preserving partial index success and current-date quote cross-checking;
- `breadth`: approved Fuyao policy followed by the existing TDX/Eastmoney chain according to current gates;
- `limits`: existing formal source order plus normalized membership/detail output and previous-session dependency;
- `sectors`: Eastmoney primary/delayed, approved Fuyao fallback, then optional same-vendor enrichment and shadow evidence under current gates;
- `activeDirection`: Eastmoney primary/delayed followed by the existing optional TDX-derived path.

Plans call source adapters in deterministic order and build ordered attempt evidence. An adapter handles one source contract: construct the request, authenticate, parse, prove the actual date, normalize fields, validate its declared capability, and return a candidate or failure. Dataset-level invariants shared across sources remain in the plan's validator.

Alternative considered: a generic configurable fallback engine with all behavior in configuration. Rejected because core sub-result retention, limits detail transactions, sector enrichment, and field authority need typed code and focused tests; configuration should choose registered policy, not become an untyped programming language.

### 4. Close the collector port before removing compatibility seams

The coordinator stops constructing concrete collectors and stops using `inspect.signature`. Bootstrap builds complete acquisition/source registries and injects a complete collector registry. A collector performs acquisition and returns a `CollectionOutcome`; the coordinator owns run/task transitions, lease/fencing validation, same-date retention, and aggregate rebuild orchestration.

Persistence is handled through a complete `DatasetCommitter` registry invoked by the coordinator with the normalized outcome and active lease. A standard committer stores simple dataset snapshots; typed core and limits committers preserve their index/session and detail/fact/manifest atomic write sets inside the existing PostgreSQL unit-of-work and fence. This avoids a universal untyped commit dictionary while keeping provider selection and task transitions outside persistence adapters. Dataset status-detail projection likewise moves behind a registered local read projector rather than remaining an optional method discovered on a provider collector. The acquisition adapter itself does not write snapshots or transition tasks.

The normal collector port remains `collect(DatasetDate) -> CollectionOutcome`. Explicit limits history preparation remains a separate application maintenance command; its subsequent collection request uses a typed refresh option at the command/coordinator boundary rather than signature inspection. Compatibility adapters must not construct a nested coordinator, acquire a second lease, or trigger a second aggregate rebuild.

During migration, a compatibility collector may wrap one unmigrated legacy chain and translate its result into the normalized outcome. Mixed migrated/unmigrated datasets must retain the same public task contract.

Alternative considered: change the application port to match the current `collect_task` implementation. Rejected because this would expose persistence records, leases, timers, and task transitions to provider code and make the current coupling permanent.

### 5. Keep the shared host policy outside pluggable HTTP engines

The current HTTP client is split conceptually into:

- a policy gateway owning normalized request identity, host pacing, request budget, single-flight, cache keys, bounded retries, `Retry-After`, circuit state, diagnostics, and redaction;
- request engines that execute exactly one permitted attempt and return an engine-neutral response or engine error.

The default engine adapts the current `requests.Session` behavior. The gateway, not an engine, loops or sleeps for retries. This prevents Scrapling or any future engine from creating a second retry budget or bypassing an open host circuit. One policy gateway and engine registry are created at the composition root and shared by all HTTP adapters in the process so same-host budgets, single-flight, and circuit state cannot fragment per adapter. Cache and single-flight keys include normalized URL, parameters, requested date, engine identity, and a non-reversible digest of authentication/tenant scope where responses can differ; credentials are never embedded in keys or persisted diagnostics.

Host policy state remains process-local, matching the current single-process/Pod support boundary. PostgreSQL leases prevent duplicate dataset/date work across triggers, but this change does not claim distributed HTTP rate limiting across Dashboard, CronJob, or any future worker. A shared cross-process limiter would require a separate capability and operational design.

Eastmoney's process-wide serial gate remains compatible with the policy gateway during migration. Fuyao's API-key request gate and business codes remain source policy, while its raw HTTP attempt is moved behind the governed engine only after contract tests prove equivalent error classification and budgets.

Alternative considered: replace `ProviderHttpClient` with Scrapling. Rejected because Scrapling does not supply the repository's exact policy contract and a replacement would mix a dependency change with provider behavior migration.

### 6. Add only a static Scrapling HTTP engine in this change

The optional engine uses Scrapling's non-browser session for explicitly allowlisted host/source pairs where authorized evidence shows ordinary requests are rejected because of HTTP/TLS client compatibility. It is not a fallback automatically selected after failure. Scrapling session retries and blocked-request escalation are disabled so one engine call equals one gateway-authorized attempt. Configuration is fail-closed: missing dependency, unknown engine, unknown host, unsupported method/body, or invalid allowlist prevents that engine assignment from starting provider work.

The default application and scheduled-collection image remain requests-only unless a separate enhanced image/profile is explicitly selected. The enhanced profile pins Scrapling and its Python fetcher dependencies but does not run `scrapling install`, download Chromium, or start a browser. Its build must be checked for Linux and supported local-development platforms, dependency conflicts, SBOM/vulnerability impact, and resource use. A future browser-backed source requires its own OpenSpec change covering worker isolation, resource limits, temporary storage, sandboxing, patch cadence, timeout, concurrency, redirects/subresources/downloads, and access-control review.

Alternative considered: install `scrapling[fetchers]` and browser dependencies in the default Dashboard image. Rejected because most current sources are JSON, binary package, authenticated API, or TCP; the extra image and browser attack surface would affect every API Pod without a proven dataset need.

### 7. Preserve formal, fallback, shadow, and enrichment lineage explicitly

Attempt evidence distinguishes:

- formal source attempts that may supply the committed candidate;
- fallback attempts that retain preceding failures and their real source;
- shadow attempts that never change the formal payload, source, checksum, task state, or snapshot;
- enrichment attempts that may fill only approved fields and never become an independent base source.

The normalized evidence is mapped back to current quality payloads and additive stored metadata so existing clients remain compatible. Raw response bodies, credentials, cookies, proxy data, authorization values, and complete challenge pages are not persisted.

Alternative considered: flatten all successful calls into a combined provider name. Rejected because it would obscure which source is authoritative and could incorrectly imply independent confirmation from same-vendor enrichment.

### 8. Enforce the architecture through contract and static gates

Tests run the same source-adapter fixtures through every applicable HTTP engine and compare normalized payload, date, quality, failure category, and redaction; only engine identity and timing may differ. Transport tests also prove cross-adapter same-host sharing, engine/auth/date cache isolation, one authoritative retry budget, and 401/403/challenge non-escalation. The architecture gate prevents application/query/coordinator modules from importing vendor clients or native engine response types, prevents direct network calls outside registered source/transport modules, and requires every stable dataset, committer, local detail projector, and selected engine to be registered at bootstrap.

Existing provider characterization tests remain the source of truth for fallback order, warnings, dates, field coverage, observations, source strings, checksums, and retention. The in-progress Fuyao sector enrichment fixtures must pass unchanged before and after sectors migration.

Alternative considered: rely on unit tests for newly written adapters only. Rejected because structural leakage and unregistered direct requests are the principal failure modes this change is intended to prevent.

## Risks / Trade-offs

- [Risk] A large seam migration changes provider behavior while moving code -> Freeze representative success, partial, fallback, date-mismatch, and failed-retained fixtures before each dataset migration; compare complete normalized and public results.
- [Risk] Moving persistence out of collectors breaks limits/core atomicity or lease fencing -> Design typed dataset commit evidence and keep writes inside the existing PostgreSQL unit-of-work with the active lease token; add fencing and transaction contract tests before switching runtime.
- [Risk] Two retry layers multiply traffic -> Make request engines single-attempt, disable engine-internal retries where possible, and assert the shared attempt/request budget in backend contract tests.
- [Risk] Alternative-engine configuration becomes a way to evade a permission block -> Require host/source allowlisting before startup, classify 401/403/challenge as non-retryable, and forbid automatic engine escalation or proxy/challenge features.
- [Risk] Optional Scrapling dependencies make clean CI and images nondeterministic -> Keep base requirements and image requests-only; use a pinned optional profile/image and a separate offline fixture matrix for the engine.
- [Risk] Engine-neutral responses copy large binary payloads -> Allow immutable bytes/text bodies with bounded diagnostic summaries; do not persist raw bodies, and retain streaming/package-specific handling when needed.
- [Risk] Provenance expansion changes snapshot checksums or API payloads -> Keep canonical dataset payload/checksum rules unchanged; store acquisition diagnostics as additive task/quality metadata only where existing contracts permit it.
- [Risk] Compatibility adapters recursively start another coordinator or lease -> Prohibit nested coordinator construction in adapters and test that one request creates one lease, one provider plan execution, one commit, and at most one aggregate rebuild.
- [Risk] Process-local host policy is mistaken for cluster-wide serialization -> Document the single-process boundary and rely on dataset/date PostgreSQL leases only for duplicate work; do not claim cross-process request-budget coordination.
- [Risk] Concurrent work changes the Fuyao sector enrichment seam -> Treat the completed enrichment contract and fixtures as a migration prerequisite, avoid changing its rollout flags, and rebase the sectors adapter extraction on the accepted behavior.
- [Trade-off] Some dataset payloads remain mappings during migration -> This avoids an all-at-once behavioral rewrite; typed dataset payload DTOs can be introduced later behind the stable envelope.
- [Trade-off] The change adds more explicit adapters and registries -> Additional files and wiring are accepted in exchange for enforceable dependency direction and independently testable source contracts.

## Migration Plan

1. Create the mandatory active exec plan and update architecture/repository/runbook/product documentation before code changes. Record baseline architecture, provider fixture, transport, collection, API, and docs-contract results.
2. Extend typed acquisition values and add engine-neutral transport request/response/failure contracts without changing runtime wiring. Adapt the existing requests path as the default engine and prove existing transport tests remain equivalent.
3. Add source adapter and acquisition plan protocols, complete registries, contract fixtures, redaction tests, and static dependency gates. Initially wrap current provider methods so public behavior is unchanged and prove the wrapper does not construct a nested coordinator.
4. Close the collector boundary: bootstrap injects collector, committer, and detail-projector registries; collectors return normalized outcomes; and the coordinator owns transitions, retention and commit/rebuild orchestration without reflection. Preserve core/limits typed atomic write sets and add mixed compatibility-path tests.
5. Extract datasets in risk order: breadth, activeDirection, sectors, core, then limits. After each cutover, run dataset fixtures, collection retention, provider-free read, public API compatibility, and PostgreSQL fencing tests before removing its legacy runtime branch.
6. Migrate remaining HTTP source calls, including Fuyao only after its API-key gate and business-code contract suite passes against the shared gateway. Remove duplicate sessions/retry loops only when the authoritative budget is proven.
7. Add the pinned, optional Scrapling static engine profile and host allowlist with no configured hosts by default. Run offline equivalence tests and a resource/image scan; do not run a real provider probe without a separate explicit authorization.
8. Remove normal runtime inheritance from the legacy all-dataset provider facade after all five plans use registered source adapters. Preserve stable import shims until repository and known external callers complete their compatibility window.
9. Run focused and full Python tests, architecture gates, strict OpenSpec validation, rules gates, and full docs contract. Record unrun optional-engine or real-network checks explicitly.

Rollback is stage-based. Each dataset retains a compatibility adapter until its characterization matrix passes, so rollback switches that dataset's composition back without changing snapshots or schema. The optional Scrapling engine rolls back by removing its allowlist/engine selection; requests remains the default. Rollback never deletes PostgreSQL data, snapshots, task history, or PVCs and does not change scheduling state.

## Open Questions

- Which authorized provider host, if any, has sufficient repeatable evidence of TLS/client-fingerprint blocking to justify the first Scrapling allowlist entry? The implementation can ship with an empty allowlist and complete offline engine tests while this evidence is gathered separately.

## Purpose

Define a provider-independent market-data acquisition contract so dataset collection can select, validate, compare, and audit heterogeneous sources without exposing vendor payloads or transport engines to collection orchestration and downstream business workflows.

## ADDED Requirements

### Requirement: Stable datasets use registered acquisition plans
The system SHALL resolve each stable market dataset through one registered acquisition plan that declares its eligible sources, capability gates, fallback ordering, and validation contract without requiring the caller to select a vendor.

#### Scenario: Registered dataset is collected
- **WHEN** a caller requests collection for `core`, `breadth`, `limits`, `sectors`, or `activeDirection`
- **THEN** the system resolves the registered plan for that dataset and executes only sources and supplemental steps eligible for the requested date and configured capabilities

#### Scenario: Dataset has no complete plan
- **WHEN** a stable dataset has no registered plan or its plan references an unavailable adapter
- **THEN** startup or collection fails closed with a classified configuration error before an external request or snapshot write occurs

### Requirement: Provider adapters return one normalized result contract
Every provider adapter SHALL return either a normalized candidate or a classified failure. A candidate MUST identify the dataset, requested date, proven actual date, provider, source, revision, observation count, quality state, warnings, fetch time, timings, field availability, and redacted provenance together with a dataset-compatible payload.

#### Scenario: Provider returns valid evidence
- **WHEN** an adapter validates a provider response for the requested dataset and date
- **THEN** it returns a normalized candidate whose identity and quality fields can be consumed without inspecting the vendor response shape or transport-engine response type

#### Scenario: Provider cannot produce valid evidence
- **WHEN** transport, permission, response-contract, date, completeness, or normalization validation fails
- **THEN** the adapter returns a classified failure with no successful payload and preserves redacted attempt diagnostics for fallback and audit

#### Scenario: Provider supplies only part of the dataset contract
- **WHEN** an eligible source omits documented optional fields while its supported fields remain valid
- **THEN** the normalized candidate keeps the unsupported fields missing, records field availability and warnings, and does not replace them with zero or inferred values

### Requirement: Acquisition adapters preserve exact-date evidence
An acquisition adapter MUST prove the actual market date permitted by its capability before returning a successful candidate and MUST NOT relabel a latest-only response, transport timestamp, cached response, or response from another date as the requested historical date.

#### Scenario: Exact historical response is validated
- **WHEN** a source supports historical collection and proves that the response belongs to the requested trading date
- **THEN** the candidate records matching requested and actual dates and may enter the dataset plan's validation and fallback flow

#### Scenario: Latest-only source is requested for history
- **WHEN** the requested date is historical and a source can provide only an unverified latest snapshot
- **THEN** the source is rejected or skipped without publishing a candidate for that historical date

#### Scenario: Cached response has another requested date
- **WHEN** an otherwise identical request has cached evidence for a different requested date
- **THEN** the adapter does not reuse that evidence as the candidate for the current request

### Requirement: Fallback sources satisfy the same dataset contract
Each source selected by an acquisition plan SHALL pass the same dataset-level identity, date, field, sample, ordering, completeness, and quality requirements applicable to that source's declared capability. A fallback MUST NOT weaken the acceptance contract merely because an earlier source failed.

#### Scenario: Primary fails and fallback succeeds
- **WHEN** the primary source returns a classified failure and the next eligible source returns a valid normalized candidate
- **THEN** the plan returns the fallback candidate with its actual source and quality while retaining the primary failure in ordered warnings and attempt evidence

#### Scenario: Fallback response is invalid
- **WHEN** a fallback response fails the dataset's date, completeness, field, sample, or ordering validation
- **THEN** the plan rejects that response and continues to another eligible source or returns a classified acquisition failure

#### Scenario: Supplemental enrichment fails
- **WHEN** an accepted base candidate permits an optional supplemental step and that step fails
- **THEN** the plan preserves the valid base candidate, records the supplemental failure and field coverage, and does not promote the supplemental source to an independent successful base source

### Requirement: Collection consumers are provider-independent
Collection orchestration and downstream business workflows SHALL consume the normalized acquisition outcome and MUST NOT require vendor client types, vendor response fields, transport-engine objects, or vendor-specific fallback branches to determine task status, retention, persistence, or materialization behavior.

#### Scenario: Equivalent candidates come from different providers
- **WHEN** two eligible adapters produce candidates satisfying the same dataset contract
- **THEN** collection orchestration applies the same commit, retention, and materialization rules while preserving each candidate's distinct source and provenance

#### Scenario: Acquisition returns a classified failure
- **WHEN** a dataset plan returns a failure without a candidate
- **THEN** collection orchestration derives `failed-retained` or `failed-missing` from same-date local state without inspecting which provider or transport engine failed

### Requirement: Shadow evidence remains non-authoritative
An enabled shadow acquisition SHALL remain separate from the formal candidate and MUST NOT overwrite its payload, source, checksum, task state, or snapshot. Shadow differences SHALL be retained only as redacted comparison evidence and warnings.

#### Scenario: Shadow candidate differs from formal candidate
- **WHEN** the formal plan returns a valid candidate and an enabled shadow source returns different values or quality
- **THEN** the formal candidate remains authoritative and the difference is recorded without changing the committed source or payload

#### Scenario: Shadow acquisition fails
- **WHEN** the formal plan succeeds and the shadow source fails or returns invalid evidence
- **THEN** collection may retain a shadow warning but does not downgrade the valid formal candidate to a failed outcome

### Requirement: Normalization is transport-engine independent
Equivalent provider responses obtained through approved request engines SHALL produce equivalent dataset payloads, quality decisions, actual-date decisions, and failure classifications. Engine identity and timing MAY differ only in diagnostics and provenance.

#### Scenario: Equivalent successful responses use different engines
- **WHEN** two approved engines return equivalent valid provider responses for the same dataset and requested date
- **THEN** the adapters produce equivalent normalized candidates apart from engine identity and timing diagnostics

#### Scenario: Equivalent failures use different engines
- **WHEN** two approved engines observe the same permission, rate-limit, malformed-response, or date-mismatch condition
- **THEN** the adapters produce the same normalized failure category and neither engine weakens fallback or validation rules

### Requirement: Acquisition provenance is auditable and redacted
The system SHALL retain enough normalized provenance to identify the selected provider, source revision, transport engine, attempt order, timing, quality decisions, and evidence integrity without storing or exposing credentials, authorization headers, proxy secrets, complete challenge pages, or other sensitive response material.

#### Scenario: Successful fallback is inspected
- **WHEN** an operator inspects a collection result produced by a fallback source
- **THEN** the stored evidence identifies the attempted sources, selected source, engine, warnings, and validation outcome without revealing secrets

#### Scenario: Credential-bearing provider fails
- **WHEN** an authenticated provider request fails
- **THEN** diagnostics contain only redacted endpoint and error evidence and do not include the credential or complete authorization value

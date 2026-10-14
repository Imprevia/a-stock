## Purpose

Define immutable, auditable THS catalog observation identities and preserve complete four-classification membership while daily market-value gaps remain explicit, nullable, and safely consumable by downstream datasets.

## ADDED Requirements

### Requirement: Catalog observation identity is independent of capability approval
The system SHALL treat the approved provider capability revision and the THS catalog observation revision as different identities. A catalog observation revision SHALL be deterministically derived from the provider, approved capability revision, exact Shanghai trading date, and canonical checksum of the complete four-classification catalog; provider and fetch timestamps MUST NOT be identity components. The fixed capability revision MUST NOT by itself be used as the catalog primary key.

#### Scenario: Same-day retry observes identical catalog content
- **WHEN** the same provider and capability revision return the same complete catalog more than once for one Shanghai trading date
- **THEN** every retry resolves to the same catalog observation revision and compatible writes are idempotent despite timestamp drift

#### Scenario: Catalog content changes under one capability revision
- **WHEN** the provider returns different complete catalog content for the same or a later Shanghai trading date without changing the approved capability revision
- **THEN** the system creates a different catalog observation revision and preserves both revisions without overwriting either one

#### Scenario: Identical catalog content is observed on another date
- **WHEN** the same complete catalog content is observed on two different Shanghai trading dates
- **THEN** the system creates distinct daily observation revisions so each ranking retains its exact-date lineage

### Requirement: Catalog checksum excludes daily market-value availability
The system SHALL calculate catalog tag counts and canonical checksum from all validated `(classification, THS code, display name)` relations for exactly `industry`, `cn_concept`, `region`, and `tszs` before reconciling daily snapshot values. Missing or null daily market values MUST NOT remove a catalog relation, alter a tag count, or change the catalog checksum.

#### Scenario: Daily all-null code set changes
- **WHEN** two observations have the same complete four-classification catalog but different codes whose daily market values are all null
- **THEN** their catalog checksum is identical and each observation retains every catalog relation

#### Scenario: Catalog membership or name changes
- **WHEN** a THS code is added, removed, moved between classifications, or renamed in the complete catalog
- **THEN** the canonical checksum changes and the new content is recorded under a new catalog observation revision

#### Scenario: Catalog contains conflicting identities
- **WHEN** a classification contains a duplicate code, conflicting names, an unsupported tag, or an invalid identity
- **THEN** the observation is rejected as an invalid catalog and daily market-value availability is not used to hide the conflict

### Requirement: Snapshot identity completeness is distinct from market-value rankability
The system SHALL validate snapshot identity, uniqueness, and exact-date lineage separately from the availability of market values. A missing snapshot identity, unexpected identity, duplicate identity, or unprovable or mismatched date SHALL reject the daily bundle before authoritative ranking or bar publication. For a valid expected exact-date row, the system SHALL independently declare `missingLiveCodes` when all six OHLC/volume/turnover bar fields are null and `missingRankingCodes` when `changePct` is null. Either gap SHALL remain explicit row evidence rather than being treated as an absent catalog member.

#### Scenario: Snapshot identity coverage is invalid
- **WHEN** an expected code has no response row, an extra or duplicate code is returned, or a row cannot prove the requested Shanghai trading date
- **THEN** the daily bundle is rejected, no incompatible ranking or bar snapshot is published, and the diagnostic identifies the failed identity/date validation without relabeling another date

#### Scenario: Expected row has no live market values
- **WHEN** an expected code has one exact-date response row but all supported daily market fields are null
- **THEN** the code remains in the catalog and ranking relations, is declared in both missing sets, and is not represented by a fabricated market fact or zero value

#### Scenario: Change percentage exists without bar fields
- **WHEN** an expected exact-date row has a valid `changePct` but every OHLC/volume/turnover field is null
- **THEN** the row remains rankable, its code is declared in `missingLiveCodes`, and no all-null daily bar is created

#### Scenario: Only some market fields are missing
- **WHEN** an exact-date response row proves some supported market fields but omits `changePct`, volume, turnover, or an OHLC field
- **THEN** the proven fields remain available, each missing field remains `null` with field-level quality, and catalog identity is unchanged

### Requirement: Partial ranking preserves complete relations and only proven bars
An accepted `industry-ranking` result SHALL contain one ranking relation for every complete catalog relation. Rankable rows SHALL be ordered by `changePct` descending and THS code ascending; rows without a proven `changePct` SHALL follow rankable rows deterministically and carry row-level `insufficient` quality and warnings. Daily bars SHALL be created only from proven market facts. For unique codes, declared bar codes and `missingLiveCodes` SHALL be disjoint and their union SHALL equal the catalog code set.

#### Scenario: Some codes have all-null market rows
- **WHEN** identity and date validation pass but one or more expected rows have all supported market fields null
- **THEN** the system atomically stores the complete catalog and ranking relations, stores bars only for proven rows, and publishes an accepted partial result with expected, rankable, bar, and missing counts

#### Scenario: Missing change percentage remains unrankable
- **WHEN** a row has a proven same-day bar but no `changePct`
- **THEN** its bar remains available, its ranking row has a null ranking value and explicit row warning, and it is not selected as a Top-N row

#### Scenario: Code is shared by classifications
- **WHEN** one THS code belongs to multiple catalog classifications
- **THEN** every classification has its own ranking relation while the proven bar or declared live-value gap is recorded once for the unique code

#### Scenario: Declared gap does not reconcile
- **WHEN** a candidate omits a catalog code from both bars and `missingLiveCodes`, declares a missing code that has a bar, or references a code outside the catalog
- **THEN** the commit is rejected atomically and no partial revision is persisted

### Requirement: One catalog revision is selected for implicit exact-date reads
An implicit exact-date THS read SHALL select one deterministic latest compatible catalog observation revision and MUST NOT merge rankings, bars, or relations from multiple revisions. A query that explicitly supplies a catalog observation revision SHALL return only that revision or report it unavailable.

#### Scenario: Same date has two catalog observations
- **WHEN** two valid catalog revisions exist for the same Shanghai trading date
- **THEN** an implicit read selects the latest compatible observation by provider timestamp, fetch timestamp, and revision identity tie-break, and downstream datasets use that same revision

#### Scenario: Caller requests an older revision explicitly
- **WHEN** a caller supplies the identity of an older retained catalog observation
- **THEN** the system returns only facts associated with that revision and does not substitute or merge the newer observation

### Requirement: Durable uniqueness follows catalog observation identity
The durable catalog store SHALL use the catalog observation revision identity as the immutable uniqueness boundary. It MUST NOT enforce a secondary uniqueness rule over provider, capability revision, catalog checksum, and fetch timestamp because that tuple omits the Shanghai trading date and can collide across valid daily observations. The migration that removes the secondary rule SHALL preserve every existing revision and relation without rewriting their identities, timestamps, checksums, or audit history.

#### Scenario: Two dates share content and fetch timestamp
- **WHEN** identical complete catalog content is stored for two Shanghai trading dates under the same provider and capability revision with the same deterministic or replayed fetch timestamp
- **THEN** both distinct date-addressed observation revisions are committed and remain independently queryable

#### Scenario: Existing fixed revision survives constraint migration
- **WHEN** the storage uniqueness migration is applied to a database containing the legacy fixed catalog revision and its related facts
- **THEN** all existing rows remain byte-for-byte logically unchanged and the legacy revision remains explicitly queryable

### Requirement: Accepted partial THS evidence remains locally serviceable
The system SHALL durably store an accepted partial THS result with its exact date, catalog observation revision, capability revision, coverage counts, row quality, warnings, checksum, and bounded missing-code diagnostics. Provider-free local queries and Chapter 01 materialization SHALL preserve nulls and partial quality, and a later failed refresh MUST NOT erase or silently upgrade that evidence.

#### Scenario: Partial result is read after restart
- **WHEN** an accepted partial THS result has been committed and the service restarts
- **THEN** exact-date status, catalog, ranking, turnover, and Chapter 01 reads use local persisted evidence without calling the provider

#### Scenario: Later refresh fails
- **WHEN** a subsequent same-date refresh fails identity, date, or provider validation after a compatible partial result was stored
- **THEN** the prior result remains readable, the new attempt remains separately auditable, and missing values remain null

### Requirement: THS historical evidence is append-only
The repair SHALL preserve existing catalog revisions, relations, rankings, bars, snapshots, capability reports, collection runs, successful attempts, failed attempts, and blocked-task records verbatim. New observations SHALL be additive; the system MUST NOT rename, update, delete, or relabel legacy evidence to make a repair appear successful.

#### Scenario: First repaired collection is committed
- **WHEN** collection succeeds or produces an accepted partial result after the repair
- **THEN** it writes a new date-and-content-addressed observation and a new collection attempt while every legacy fixed revision and prior audit record remains readable and unchanged

#### Scenario: Legacy fixed revision is queried
- **WHEN** an administrative or explicit-revision read requests a previously stored fixed catalog revision
- **THEN** its original relations and associated facts remain available without being interpreted as a new date-and-content-addressed observation

## ADDED Requirements

### Requirement: Compatible partial THS prerequisites remain executable
The collection coordinator SHALL treat an accepted same-date, same-catalog-revision THS result with declared market-value gaps as a compatible partial prerequisite. `sector-turnover` SHALL consume only proven bars and report partial coverage. `sector-breadth` SHALL select only rankable rows and SHALL continue when every classification has at least the configured Top-N count of valid candidates. Identity/date failures, an incompatible catalog revision, or insufficient valid candidates MUST remain explicit insufficient or blocked outcomes rather than being presented as complete.

#### Scenario: Ranking is partial only because live values are missing
- **WHEN** `industry-ranking` commits a compatible partial result with complete relations and declared `missingLiveCodes`
- **THEN** `sector-turnover` executes against the proven same-revision bars, reports the omitted codes and coverage, and is not marked dependency-blocked

#### Scenario: Every classification has enough rankable candidates
- **WHEN** compatible ranking and turnover inputs are partial but each classification still has at least the configured number of rows with proven ranking values
- **THEN** `sector-breadth` excludes unrankable rows, selects the stable Top N from valid candidates, executes once, and preserves partial lineage

#### Scenario: One classification lacks enough rankable candidates
- **WHEN** a classification has fewer valid ranking candidates than its configured Top N
- **THEN** `sector-breadth` is `insufficient`, reports that classification and its valid/required counts, and does not label a shorter list as complete Top N

#### Scenario: Prerequisite revision is incompatible
- **WHEN** an otherwise available prerequisite belongs to another date or catalog observation revision
- **THEN** the dependent task is blocked with a revision-mismatch reason and does not merge or invoke downstream work against incompatible evidence

#### Scenario: Ranking validation fails before publication
- **WHEN** the ranking collector rejects missing identities, duplicate identities, or wrong-date evidence and has no compatible exact-date retained result
- **THEN** dependent THS tasks remain blocked or insufficient while unrelated sibling datasets continue independently

### Requirement: THS task diagnostics are stable bounded and provider-free
THS collection results SHALL expose optional machine-readable diagnostics in addition to human-readable warnings. Diagnostics SHALL contain a stable reason code, failure stage, exact date, capability revision and catalog observation revision when known, expected/observed/rankable/bar counts, bounded missing-code samples with total counts, retryability, and upstream dependency details when blocked. Status reads MUST use local state only, MUST remain backward compatible with legacy text-only warnings, and MUST NOT expose credentials, signed URLs, sensitive headers, or raw provider responses.

#### Scenario: Partial ranking status is displayed
- **WHEN** an accepted partial ranking has live-value gaps
- **THEN** its status reports `THS_LIVE_VALUES_MISSING`, usable and expected counts, catalog revision, and a bounded missing-code sample without calling the provider

#### Scenario: Daily snapshot validation fails
- **WHEN** collection rejects missing, duplicate, or wrong-date snapshot identities
- **THEN** its attempt reports `THS_DAILY_SNAPSHOT_INSUFFICIENT`, the validation stage, bounded identity counts, and retryability without persisting the raw response

#### Scenario: Catalog revision identity collides
- **WHEN** one derived catalog observation identity is presented with content that does not match its stored checksum
- **THEN** the attempt reports `THS_CATALOG_REVISION_COLLISION` with the revision and existing/new checksum summaries and does not overwrite the stored revision

#### Scenario: Dependent task is blocked
- **WHEN** a THS task cannot run because an upstream result is insufficient or revision-incompatible
- **THEN** diagnostics report `THS_DEPENDENCY_INSUFFICIENT` or `THS_DEPENDENCY_REVISION_MISMATCH` plus the upstream dataset, task status, exact date, and catalog revision when known

#### Scenario: Legacy warning is read
- **WHEN** a stored task predates typed diagnostics and contains only a human-readable warning
- **THEN** the status API returns the warning unchanged, leaves optional diagnostic fields absent, and performs no provider request

#### Scenario: Missing-code list exceeds the display limit
- **WHEN** a diagnostic contains more missing identities than the configured bounded sample size
- **THEN** the response reports the full missing count and only the bounded deterministic sample without truncating the count or leaking the raw payload

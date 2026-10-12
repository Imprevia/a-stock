## ADDED Requirements

### Requirement: Current-day sector observations are isolated from point-in-time industry analysis
The system SHALL retain every accepted current-day sector ranking under its provider taxonomy, provider identity, and proven observation date. Provider sector codes and normalized names MUST NOT be relabeled as stable Shenwan industry identities or used to infer historical constituent membership. An observation MAY be associated with a Shenwan analysis identity only through an explicit, versioned mapping valid for the requested date; an absent, ambiguous, or conflicting mapping SHALL remain unlinked without removing the original observation.

#### Scenario: Current-day provider ranking has no Shenwan mapping
- **WHEN** an accepted ranking row has a valid provider identity and date but no approved exact-date Shenwan mapping
- **THEN** the row remains available as an observation while continuity analysis does not treat its identity as Shenwan

#### Scenario: Versioned mapping links an observation
- **WHEN** exactly one approved mapping revision links a provider identity to a Shenwan identity for the requested date
- **THEN** both identities, the mapping revision, and effective date are retained without replacing the provider identity

#### Scenario: Mapping is ambiguous or date-incompatible
- **WHEN** multiple Shenwan identities match or the mapping is not effective on the requested date
- **THEN** no analysis association is produced and neither a current mapping nor a normalized-name guess is substituted

### Requirement: Sector continuity inputs independently prove the requested exact date
The system SHALL accept continuity inputs only when the Shenwan classification, effective membership, security facts, benchmark facts, and trading-session identity each prove the requested date. A current-day ranking, undated latest response, current membership, other-date snapshot, or numeric zero MUST NOT fill a missing historical fact. These rules SHALL NOT weaken existing latest-only restrictions for sector-ranking providers.

#### Scenario: Exact-date historical facts are available
- **WHEN** a historical session has point-in-time Shenwan membership and all required market and benchmark facts for the same date
- **THEN** those facts are eligible for continuity analysis with source and version lineage retained

#### Scenario: Only a latest ranking is available
- **WHEN** a historical session has a current or undated ranking but lacks exact-date analysis facts
- **THEN** historical analysis remains `insufficient`, no latest row is relabeled, and no latest-only ranking endpoint is called for that date

#### Scenario: One input family is incomplete
- **WHEN** classification, membership, security, benchmark, or calendar evidence lacks required coverage or date proof
- **THEN** the affected input remains missing with a structured warning rather than being inferred

### Requirement: Sector observation and analysis quality remain independently auditable
The system SHALL preserve separate quality and lineage for current-day provider observations and derived Shenwan continuity analysis. Metadata SHALL distinguish source identity, actual date, observations, identity and constituent coverage, history, data version, classification version, calculation version, evidence references, and warnings. Analysis failure SHALL NOT hide a valid observation, and failed analysis refresh SHALL retain only a compatible result for the same exact date.

#### Scenario: Observation succeeds while analysis is insufficient
- **WHEN** a provider ranking is valid but membership, history, or another critical analysis input is incomplete
- **THEN** the observation remains available and analysis is separately `insufficient` with its gaps

#### Scenario: Analysis refresh fails with a compatible same-date result
- **WHEN** refresh fails and a successful analysis exists for the same date and version contract
- **THEN** the prior result is retained and the attempt is exposed as `failed-retained`

#### Scenario: Analysis refresh fails without a compatible same-date result
- **WHEN** refresh fails and no compatible successful analysis exists for the date
- **THEN** analysis is `failed-missing` or `insufficient` and no other date is substituted

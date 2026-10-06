## MODIFIED Requirements

### Requirement: Sector endpoints use the unified transport without changing fallback order
The system SHALL send Eastmoney sector ranking and supplemental field requests through the unified transport while preserving the formal source order: primary `push2`, delayed `push2delay`, and only then the capability-gated Fuyao fallback. The `data.eastmoney.com/dataapi/bkzj/getbkzj` endpoint SHALL be treated as an optional same-vendor enrichment request after an accepted Fuyao result, not as an independent provider or a replacement for the formal fallback order.

#### Scenario: Primary sector host is cooling down
- **WHEN** the primary host is in transport cooldown
- **THEN** the collector skips repeated primary attempts for that request and proceeds to the existing delayed endpoint fallback with an auditable warning

#### Scenario: Delayed sector response is cached
- **WHEN** an identical delayed sector request is repeated within the request TTL
- **THEN** the cached response is used without changing the reported source or fallback quality status

#### Scenario: Supplemental Eastmoney host is unavailable
- **WHEN** the dataapi enrichment request fails, is rate limited, or returns an invalid payload after its bounded recovery budget
- **THEN** the accepted Fuyao four-field result remains usable, the sector quality remains degraded/fallback, and the enrichment warning is retained without converting the base result to a provider failure

### Requirement: Fuyao sector fallback exposes only supported fields
The system SHALL map Fuyao THS rows to the compatible `SectorRow` shape using code, name, change percentage, and turnover. Main net flow, main net flow percentage, advancing/declining counts, and leader name MAY be filled only by a separately validated same-vendor enrichment row with an approved identity match; otherwise they MUST remain `null`. Enrichment MUST carry a warning and MUST NOT make the result appear equivalent to a complete independent sector provider.

#### Scenario: Supported THS fields are present
- **WHEN** a valid snapshot row contains a unique THS code, name, change percentage, and turnover
- **THEN** those four values are exposed without synthesizing unsupported fields

#### Scenario: Unsupported industry fields are absent
- **WHEN** Fuyao does not return fund-flow, breadth, or leader fields and no approved enrichment row matches
- **THEN** the API leaves those fields `null`, reports the missing-field warning, and does not display a code as a leader name or fill a numeric field with zero

#### Scenario: Valid supplemental row matches a Fuyao industry
- **WHEN** the dataapi row passes field, scale, current-date, and identity validation for a Fuyao row
- **THEN** only the missing compatible fields are filled, the Fuyao code/name/change/amount remain authoritative, and the response records the supplemental source and match coverage

#### Scenario: Supplemental row has no approved identity match
- **WHEN** an Eastmoney row cannot be joined to a Fuyao industry through the approved mapping or exact normalized name policy
- **THEN** no field is copied to that Fuyao row and the unmatched row contributes to a visible coverage warning

## ADDED Requirements

### Requirement: Sector dataapi enrichment is latest-only and exact-date constrained
The system SHALL request the dataapi enrichment only for the current Shanghai market date whose latest-only eligibility has been established by the collection request. It MUST reject historical enrichment and MUST NOT use an undated latest response to backfill another `as_of` value.

#### Scenario: Current-date Fuyao result is enriched
- **WHEN** a Fuyao sector result belongs to the current Shanghai market date and the collection request is latest-only eligible
- **THEN** the system may request the dataapi fields and attach the enrichment to that same collection result

#### Scenario: Historical sector collection is requested
- **WHEN** the selected `as_of` is not the current Shanghai market date
- **THEN** the system does not call the undated dataapi endpoint and preserves the existing historical latest-only rejection or missing semantics

#### Scenario: Dataapi response has no independently provable business date
- **WHEN** the dataapi response lacks acceptable current-date evidence or the request is outside the approved settlement/current-date boundary
- **THEN** the response is not used to fill fields, and the Fuyao base result remains available with a date-evidence warning

### Requirement: Supplemental sector fields are normalized and coverage-audited
The system SHALL request an explicit dataapi field set covering `f62`, `f184`, `f104`, `f105`, and `f128`, validate raw types and field scales before mapping them to `SectorRow`, and expose per-field match coverage and the mapping revision in quality metadata. Missing, malformed, or unsupported fields MUST remain `null`.

#### Scenario: Dataapi returns all requested fields
- **WHEN** the response contains valid industry identities and valid values for the requested fields
- **THEN** the system normalizes the values, fills only compatible nulls, and reports requested rows, matched rows, field coverage, source endpoint, and mapping revision

#### Scenario: Dataapi percentage scale differs from the canonical schema
- **WHEN** `f3` or `f184` uses an integerized percentage representation rather than the canonical floating-point percentage
- **THEN** the system applies the reviewed normalization rule before validation and rejects ambiguous scale rather than persisting a silently distorted percentage

#### Scenario: Dataapi covers fewer industries than Fuyao
- **WHEN** the dataapi response covers only a subset of the accepted Fuyao catalog
- **THEN** matched rows receive only validated supplemental fields, unmatched rows retain `null`, and quality remains `fallback`/`partial` with the coverage gap visible

### Requirement: Sector identity joins are explicit and non-inferential
The system SHALL keep the Fuyao THS identity as the canonical sector identity. Eastmoney `BK` codes MUST NOT be treated as THS codes; joins SHALL use an approved versioned mapping or an exact normalized-name match with collision detection, and ambiguous names MUST remain unmatched.

#### Scenario: Unique normalized-name match
- **WHEN** exactly one Eastmoney row matches a Fuyao name after the approved normalization rules
- **THEN** the row may be used for supplemental fields and the match method is recorded

#### Scenario: Name collision or taxonomy conflict
- **WHEN** multiple Eastmoney rows match a Fuyao name or the row's change/amount sanity check conflicts beyond the accepted tolerance
- **THEN** the row is rejected for enrichment and the conflict is recorded as a warning

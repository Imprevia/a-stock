## ADDED Requirements

### Requirement: Limits pools preserve valid membership independently of enrichment

The versioned `limit_up`, `limit_down`, and `failed_limit_up` pool resources SHALL return exact-date members with valid security identity even when optional board, ST, listing-window, or limit-regime attributes are unavailable or a stored exclusion reason applies only to legacy promotion eligibility. They MUST exclude malformed or conflicting identities, missing or conflicting actual dates, invalid duplicates, and conflicting pool memberships. Membership visibility MUST NOT imply that a row has valid consecutive-board data or complete advanced classification attributes.

#### Scenario: Advanced attributes are missing
- **WHEN** a stored exact-date pool member has valid identity but is excluded from legacy promotion eligibility because board or listing-window evidence is missing
- **THEN** the corresponding pool returns that member with its stored nullable attributes, source, row quality and exclusion warning preserved

#### Scenario: Failed and down members are outside legacy promotion scope
- **WHEN** a valid exact-date failed-limit-up or limit-down member has a legacy exclusion reason indicating that it is outside the promotion pool
- **THEN** the member remains visible in its own pool without being presented as a promoted security

#### Scenario: Identity or date evidence is invalid
- **WHEN** a stored row has missing identity, identity conflicts, missing or mismatched actual date, an invalid duplicate marker, or conflicting pool membership
- **THEN** that row is excluded from pool results and its exclusion is not concealed by upgrading the stored dataset quality

#### Scenario: Consecutive-board evidence is unavailable
- **WHEN** a valid limit-up member has no valid consecutive-board count
- **THEN** the pool returns the member with the original missing value and does not invent a first-board or higher-tier assignment

### Requirement: Promoted pool agrees with the validated adjacent-session aggregate

The versioned `promoted` pool SHALL represent the same identity intersection as the stored validated basic promotion aggregate: valid closing-limit-up members from the requested session and its proven immediately preceding trading session. Both dated memberships MUST be complete, use the supported promotion rule version, and be bound to their matching aggregate checksums. Legacy enrichment eligibility MUST NOT be an additional inclusion requirement. Missing or invalid prerequisites MUST NOT produce a successful promoted collection; stored integrity failures MUST retain the established integrity error contract.

#### Scenario: Basic promotion is valid despite incomplete enrichment
- **WHEN** both complete adjacent-session limit-up memberships and their aggregate bindings are valid, and shared members lack optional enrichment attributes
- **THEN** the promoted pool contains those shared valid members and its full paginated count agrees with the promotion numerator for the same revision

#### Scenario: Previous membership contains invalid rows
- **WHEN** a current valid closing-limit-up member matches a previous row whose identity or actual date is invalid
- **THEN** the previous row cannot establish promotion and the response retains the applicable incomplete-evidence status

#### Scenario: Adjacent-session prerequisites are unavailable
- **WHEN** the immediately previous trading session is unproven, either dated membership is incomplete, or its rule version is unsupported
- **THEN** the promoted resource returns explicit missing or insufficient evidence without a successful member list, without searching older sessions, and without collecting data

#### Scenario: Stored promotion binding is corrupt
- **WHEN** the stored membership checksum does not match its bound limits aggregate
- **THEN** the resource returns the existing stable integrity-unavailable response and performs no writes or external provider calls

#### Scenario: Previous complete membership is empty
- **WHEN** the preceding trading session has a proven complete but empty limit-up membership
- **THEN** the promoted collection is empty, the promotion ratio remains null with zero-denominator insufficient quality, and no empty result is reinterpreted as missing collection

### Requirement: Restored limits membership preserves bounded read and quality contracts

Limits pool reads SHALL retain deterministic identity ordering, server-enforced limits, revision-bound cursors, exact-date metadata, source, observation semantics and refresh warnings. Pool filtering MUST occur before page boundaries are applied, so invalid stored rows cannot hide valid rows on later pages. Dataset observation counts MUST remain distinct from the current page's returned count; observations alone MUST NOT be represented as verified tier membership. All restored reads MUST remain provider-free and write-free.

#### Scenario: Valid and invalid stored rows span multiple pages
- **WHEN** a client reads all pages under one revision from a pool containing both valid members and excluded rows
- **THEN** it receives each valid member once in stable order without invalid rows, skipped valid members, or premature pagination termination

#### Scenario: Same-date evidence was retained after refresh failure
- **WHEN** restored members are read from a same-date retained snapshot following a failed refresh
- **THEN** the response keeps the stored retained or degraded quality and refresh warning rather than presenting a new collection success

#### Scenario: Pool is proven empty
- **WHEN** the requested date has an explicitly complete pool with zero valid members
- **THEN** the collection returns a true empty result with its stored quality, without substituting another date or creating members

#### Scenario: Revision changes while reading restored members
- **WHEN** a pool continuation or pinned follow-up request uses a replaced snapshot revision
- **THEN** the API returns the existing revision-conflict response rather than mixing member sets

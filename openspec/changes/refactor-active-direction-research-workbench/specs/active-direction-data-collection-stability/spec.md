## MODIFIED Requirements

### Requirement: Every active-direction source satisfies the same Top-N contract
The system MUST validate every primary, delayed, or approved locally derived candidate payload before deriving or storing active-direction evidence, MUST NOT weaken validation for a fallback source, SHALL preserve the validated ordered Top-30 rows as the research sample, and SHALL retain the first 10 rows as the backward-compatible `topStocks` display field.

#### Scenario: Delayed endpoint returns enough valid sorted rows
- **WHEN** the delayed endpoint returns at least 30 object rows with a security code, security name, numeric turnover amount, and non-increasing turnover order
- **THEN** the system preserves the first 30 validated rows for research, derives the industry cluster from those rows, and exposes their first 10 rows through the legacy `topStocks` field

#### Scenario: Delayed endpoint returns too few valid rows
- **WHEN** fewer than 30 delayed rows contain all required code, name, and turnover fields
- **THEN** the payload is rejected and no successful snapshot is written from it

#### Scenario: Delayed endpoint returns unsorted rows
- **WHEN** any later valid delayed row has a greater turnover amount than the preceding valid row
- **THEN** the payload is rejected rather than locally reordered and represented as a provider-ranked result

#### Scenario: Provider returns a keyed diff object
- **WHEN** either endpoint returns `data.diff` as an object keyed by row index instead of an array
- **THEN** the system normalizes its values and applies the same field, sample, ordering, and Top-30 preservation validation

#### Scenario: Approved TDX fallback supplies unordered full-market rows
- **WHEN** the approved TDX-derived fallback has exact-date, complete, uniquely identified rows with valid close and turnover facts
- **THEN** the system applies the documented stable local turnover ordering, preserves the resulting Top 30 with derived lineage, and exposes the first 10 through `topStocks`

#### Scenario: Legacy consumer reads only Top-10 fields
- **WHEN** an existing consumer reads active-direction state, summary, quality, and `topStocks`
- **THEN** it receives the same compatible field names and at most 10 ordered display rows without needing the research-workbench contract

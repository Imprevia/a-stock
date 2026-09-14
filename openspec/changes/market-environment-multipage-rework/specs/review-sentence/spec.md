# Review Sentence Specification

## ADDED Requirements

### Requirement: Market-level structured sentence
The system SHALL generate a `ReviewSentence` from market-level seven-item evidence rather than the first index. It SHALL expose ordered `ReviewSentenceSegment` entries with a stable key, label, rendered value, quality status, and optional missing reason, plus a complete sentence suitable for copying. Missing inputs SHALL render as `数据不足` in place and SHALL NOT be fabricated or persisted.

#### Scenario: Complete evidence yields a copyable sentence
- **WHEN** all seven market evidence values are valid
- **THEN** the response contains all ordered segments with `status=available` and a non-empty `fullSentence` containing their rendered values

#### Scenario: One evidence item is missing
- **WHEN** one market evidence item is unavailable with a reason
- **THEN** only that segment renders `数据不足` with its reason while the remaining segments remain present and the sentence stays copyable

### Requirement: Additive compatibility
The system SHALL retain existing `summarySentence` and index-level fields while exposing `reviewSentence` additively. Generating or copying a sentence SHALL NOT create a review-record row or any persistent user-input state.

#### Scenario: Legacy summary remains available
- **WHEN** an older consumer reads the chapter response
- **THEN** `summarySentence` and existing index fields remain present, while the new structured sentence is ignored safely.

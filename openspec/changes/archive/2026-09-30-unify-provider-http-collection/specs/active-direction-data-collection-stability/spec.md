# Spec Delta

## ADDED Requirements

### Requirement: Active-direction endpoints use the unified transport without weakening validation

The system SHALL send active-direction primary and delayed endpoint requests through the unified transport while preserving the existing Top-N field, sample-count, ordering, fallback, and failure-retention validation.

#### Scenario: Primary active-direction host is cooling down

- **WHEN** the primary host is in transport cooldown
- **THEN** the collector proceeds to the delayed endpoint or configured TDX-derived fallback without uncontrolled primary retries

#### Scenario: Invalid response is not cached as success

- **WHEN** an active-direction response fails field, sample, or ordering validation
- **THEN** the response is not stored as a successful request cache entry and the existing fallback chain remains responsible for recovery

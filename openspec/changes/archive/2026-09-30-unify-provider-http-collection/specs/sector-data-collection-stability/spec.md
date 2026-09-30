# Spec Delta

## ADDED Requirements

### Requirement: Sector endpoints use the unified transport without changing fallback order

The system SHALL send both Eastmoney sector endpoint requests through the unified transport while preserving primary-first ordering, bounded recovery, delayed fallback, and existing quality warnings.

#### Scenario: Primary sector host is cooling down

- **WHEN** the primary sector host is in transport cooldown
- **THEN** the collector skips repeated primary attempts for that request and proceeds to the existing delayed endpoint fallback with an auditable warning

#### Scenario: Delayed sector response is cached

- **WHEN** an identical delayed sector request is repeated within the request TTL
- **THEN** the cached response is used without changing the reported source or fallback quality status

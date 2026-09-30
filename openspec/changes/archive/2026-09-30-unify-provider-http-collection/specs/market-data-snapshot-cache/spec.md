# Spec Delta

## ADDED Requirements

### Requirement: Request cache does not weaken exact-date snapshot semantics

The system SHALL keep request-layer TTL entries separate from durable dataset snapshots, and request-layer cache hits MUST NOT change source, quality, freshness, or exact-date validation metadata.

#### Scenario: Short TTL request is reused

- **WHEN** an identical live request is repeated within its TTL
- **THEN** the provider response is reused without another upstream call and the durable snapshot contract remains unchanged

#### Scenario: Request cache expires

- **WHEN** a request-layer TTL expires or the response was unsuccessful
- **THEN** the next request may contact the provider and no failed response is stored as successful evidence

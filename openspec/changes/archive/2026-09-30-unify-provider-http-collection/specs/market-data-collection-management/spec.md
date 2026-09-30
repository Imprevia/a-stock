# Spec Delta

## ADDED Requirements

### Requirement: Collection tasks share provider transport controls

The system SHALL apply the unified provider transport controls to every external request started by a collection task while preserving independent task status and same-date failure retention.

#### Scenario: One task exhausts a host cooldown

- **WHEN** a provider host is cooling down while one collection task fails
- **THEN** sibling dataset tasks continue independently, and the failed task records the classified warning without removing successful snapshots

#### Scenario: Duplicate task calls the same request

- **WHEN** a duplicate collection request reaches an in-flight identical provider request
- **THEN** it joins the single-flight request and does not emit another upstream call

# Index Synchronization Assessment Delta

## MODIFIED Requirements

### Requirement: Next-session review does not rewrite synchronization assessment
The dashboard SHALL keep the observed `syncPattern` and existing `synchronizationAssessment` unchanged while displaying a separate exact next-session comparison. The comparison SHALL be read-only and SHALL expose changed evidence or an explicit pending/insufficient boundary.

#### Scenario: Posterior change is shown separately
- **WHEN** a next real session has exact core and breadth evidence
- **THEN** Section 01 and Section 09 show deltas from the comparison endpoint without replacing the current synchronization pattern or conclusion.

## ADDED Requirements

### Requirement: Offline pull request gate
The system SHALL run registry schema validation, coverage, documentation synchronization, deterministic fixture and golden tests, evidence verification tests, pytest, and the full docs contract in pull requests without network access.

#### Scenario: Pull request changes a threshold without provenance
- **WHEN** a pull request introduces a rule threshold without allowed provenance
- **THEN** the pull request workflow fails before evaluation

#### Scenario: Network is unavailable in pull request CI
- **WHEN** the pull request workflow has no usable market data network
- **THEN** all required checks still complete using committed fixtures

### Requirement: After-market scheduled execution
The system SHALL provide a scheduled and manually dispatchable workflow that creates a real-data snapshot, evaluates chapter 01, verifies the evidence bundle, and uploads the bundle as an Artifact.

#### Scenario: Provider is degraded
- **WHEN** the preferred provider fails and a fallback is used or required data is unavailable
- **THEN** the workflow uploads evidence marked `degraded` or `insufficient` and does not publish a successful market conclusion

### Requirement: Tracked evidence summaries
The system SHALL keep small validation indexes and monthly SHA-256 summaries in Git while keeping complete snapshots, traces, and results in CI Artifacts.

#### Scenario: Monthly summary is generated
- **WHEN** scheduled evidence exists for a calendar month
- **THEN** the summary lists evidence identifiers, dates, rule-set versions, Git SHAs, statuses, and manifest hashes without embedding large raw inputs

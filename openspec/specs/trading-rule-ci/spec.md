# Trading Rule CI Specification

## Purpose

TBD: Define continuous-integration and scheduled-execution contracts for trading rules.

## Requirements

### Requirement: Offline pull request gate
The system SHALL run registry schema validation, coverage, documentation synchronization, deterministic fixture and golden tests, evidence verification tests, and the full docs contract in pull requests without network access. The complete backend test suite and the repository test ratchet SHALL be executed by the repository test gate that also runs on pull requests, so that the suite executes exactly once per pull request. This gate MUST still fail the pull request when any rule-specific check it owns fails.

#### Scenario: Pull request changes a threshold without provenance
- **WHEN** a pull request introduces a rule threshold without allowed provenance
- **THEN** the pull request workflow fails before evaluation

#### Scenario: Network is unavailable in pull request CI
- **WHEN** the pull request workflow has no usable market data network
- **THEN** all required checks still complete using committed fixtures

#### Scenario: A rule-specific check fails while another gate owns the complete suite
- **WHEN** a rule registry, coverage, documentation synchronization, golden replay, or evidence check fails in a pull request and the complete suite is executed by another gate
- **THEN** this gate fails the pull request on its own result and does not defer its verdict to that other gate

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

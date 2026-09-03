# Market Data Snapshot Cache Specification

## Purpose

为市场环境 API 提供按交易日持久化、可预计算且可审计的数据集快照，使盘后研究请求优先读取本地已验证结果，并在数据过期或 provider 失败时保持明确的质量语义。

## Requirements

### Requirement: Durable trading-date snapshots
The system SHALL persist each supported market dataset by dataset identifier and exact trading date, together with its normalized payload, source, fetch time, observation count, quality status, warnings, and integrity checksum.

#### Scenario: Snapshot survives a service restart
- **WHEN** a dataset snapshot has been stored successfully and the API service restarts
- **THEN** a request for the same dataset and trading date reads the stored snapshot without calling the external provider

#### Scenario: Historical dates remain isolated
- **WHEN** a request targets a trading date for which no exact snapshot exists
- **THEN** the system does not substitute a snapshot captured for another date and returns the dataset as missing or insufficient

### Requirement: Dataset-specific acquisition
The system SHALL acquire only the observations required by each dataset instead of requiring one complete all-market stock response for every Chapter 01 dataset.

#### Scenario: Breadth collection avoids the incomplete full-market attempt
- **WHEN** market breadth is refreshed
- **THEN** the collector uses the validated exact breadth collection path directly and does not first request a nominal full-market response known to be capped or incomplete

#### Scenario: Active direction uses ranked Top-N observations
- **WHEN** active direction is refreshed
- **THEN** the collector requests a server-ranked turnover Top-N sample large enough to calculate the documented top-30 cluster and top-10 display results without downloading every A-share row

### Requirement: After-market precomputation
The system SHALL provide an explicit after-market refresh operation that collects, validates, derives, and atomically stores all configured snapshot-backed datasets for a requested trading date.

#### Scenario: Successful after-market refresh
- **WHEN** an operator runs the refresh operation for a completed trading date and all required validations pass
- **THEN** the operation stores the normalized inputs and derived API results and reports the refreshed datasets, observation counts, sources, durations, and final quality states

#### Scenario: Partial refresh failure
- **WHEN** one configured dataset fails while other datasets refresh successfully
- **THEN** successful datasets are committed independently, the failed dataset is reported as degraded or insufficient, and the operation exits with an auditable partial-failure result

### Requirement: Dataset freshness policy
The system SHALL evaluate freshness independently for each dataset and SHALL distinguish fresh, stale, missing, and refreshing cache states without changing the underlying evidence values.

#### Scenario: Fresh snapshot is served directly
- **WHEN** an exact-date snapshot is within its configured freshness window
- **THEN** the API returns it immediately without calling the provider

#### Scenario: Stale snapshot is served while refreshing
- **WHEN** an exact-date snapshot exists but its freshness window has expired
- **THEN** the API returns the last successful snapshot immediately with stale quality metadata and initiates or joins a refresh

#### Scenario: Completed after-market snapshot remains reusable
- **WHEN** a successful snapshot has been confirmed after the configured market settlement time
- **THEN** subsequent requests for that trading date continue to reuse it until an explicit forced refresh or retention removal

### Requirement: Single-flight refresh coordination
The system SHALL ensure that concurrent refresh requests for the same dataset and trading date result in at most one active provider collection across API workers sharing the same snapshot store.

#### Scenario: Concurrent cold requests share one refresh
- **WHEN** multiple requests simultaneously miss the same dataset and trading-date snapshot
- **THEN** one requester acquires the refresh lease and the others reuse the stored result after completion rather than issuing duplicate provider calls

#### Scenario: Abandoned refresh lease expires
- **WHEN** a refresher terminates without releasing its lease
- **THEN** another requester can acquire the lease after the bounded lease period and retry collection

### Requirement: Auditable degradation
The system SHALL retain the last successful exact-date snapshot when a refresh fails and SHALL expose additive cache metadata that identifies snapshot time, cache state, freshness, and refresh warning.

#### Scenario: Refresh fails with a previous snapshot
- **WHEN** a stale exact-date snapshot exists and the external provider refresh fails
- **THEN** the API returns the prior evidence values, marks the cache state stale, and records the refresh failure without converting missing values to zero

#### Scenario: Refresh fails without a previous snapshot
- **WHEN** no exact-date snapshot exists and collection fails
- **THEN** the API returns the existing missing, failed, or insufficient evidence contract with provider warnings and does not fabricate a snapshot

### Requirement: API compatibility and warm-read performance
The system SHALL preserve the existing market-environment endpoint paths and existing response fields, and any cache metadata SHALL be additive and optional for existing consumers.

#### Scenario: Existing consumer ignores cache metadata
- **WHEN** a consumer parses only the response fields available before this change
- **THEN** successful core and Chapter 01 responses remain valid without requiring consumer changes

#### Scenario: Warm Chapter 01 read avoids network latency
- **WHEN** core data and the requested Chapter 01 dataset are already stored and fresh
- **THEN** the request performs no external provider call and completes within 500 milliseconds in the local performance verification environment

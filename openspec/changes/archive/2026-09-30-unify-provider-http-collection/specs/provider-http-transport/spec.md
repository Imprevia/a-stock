# Spec Delta

## Purpose

Provide one auditable HTTP transport contract for external market providers so that
request pacing, retries, caching, user-agent selection, and host recovery are consistent.

## ADDED Requirements

### Requirement: Provider requests use host-scoped transport policy

The system SHALL route external market-provider requests through a host-scoped transport policy that applies connection/read timeouts, connection reuse, a minimum interval with jitter, and a bounded request budget.

#### Scenario: Direct provider request is issued

- **WHEN** a provider requests JSON, text, or binary data from an external host
- **THEN** the transport applies the host policy before sending the request and returns the response or a classified provider failure

#### Scenario: Concurrent requests target one host

- **WHEN** multiple provider workers request the same host concurrently
- **THEN** request starts are serialized by that host policy and no uncontrolled burst is emitted

### Requirement: Transport retries only recoverable failures

The system SHALL retry connection failures, read failures, HTTP 408, HTTP 429, and HTTP 5xx responses within a bounded budget, using exponential backoff with jitter and honoring a valid `Retry-After` value when present.

#### Scenario: Recoverable failure later succeeds

- **WHEN** a request receives a recoverable failure and a later attempt succeeds within the retry budget
- **THEN** the transport returns the successful response and exposes retry timing in diagnostic metadata

#### Scenario: Permission or contract failure occurs

- **WHEN** a request receives HTTP 401/403, another non-retryable 4xx response, or an invalid response contract
- **THEN** the transport performs no blind retry and returns a non-retryable classified failure

### Requirement: Host sessions use stable modern user agents

The system SHALL select a modern browser user agent from an injectable pool per host session, keep it stable for that session, and rotate it only when the session is recreated or recovery probing creates a new session.

#### Scenario: Requests share a host session

- **WHEN** multiple requests use the same host session
- **THEN** they use the same selected user agent and standard JSON-compatible request headers

#### Scenario: A host session is recreated

- **WHEN** a host session is recreated after recovery or transport reset
- **THEN** a new user agent may be selected from the approved pool without using legacy browser identities

### Requirement: Transport deduplicates and caches safe requests

The system SHALL coalesce concurrent identical GET requests and MAY serve a successful response from a short in-process TTL cache; cache keys MUST include the normalized URL, parameters, and any exact requested date.

#### Scenario: Identical requests overlap

- **WHEN** identical GET requests arrive concurrently before the first response completes
- **THEN** only one upstream request is issued and all callers receive the same result

#### Scenario: Different exact dates are requested

- **WHEN** two otherwise identical historical or package requests use different requested dates
- **THEN** they do not share a cache entry

### Requirement: Host failures enter bounded recovery cooldown

The system SHALL enter a short host cooldown after repeated recoverable failures, route subsequent calls to existing provider fallbacks during cooldown, and allow one controlled half-open probe after the cooldown.

#### Scenario: Host repeatedly fails

- **WHEN** a host reaches the configured recoverable-failure threshold
- **THEN** subsequent calls fail fast or use the existing fallback until the cooldown expires

#### Scenario: Half-open probe succeeds

- **WHEN** the first controlled probe after cooldown succeeds
- **THEN** the host returns to normal request service and clears the cooldown state

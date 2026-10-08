## ADDED Requirements

### Requirement: Provider transport supports registered request engines
The system SHALL execute every external HTTP request through a registered request engine selected by explicit host and source capability while preserving one engine-neutral response and failure contract. The existing requests engine SHALL remain the default when no alternative engine is explicitly approved.

#### Scenario: Default provider request is issued
- **WHEN** a provider request has no approved enhanced-engine configuration
- **THEN** the transport uses the default request engine and returns the same normalized transport response or classified failure contract

#### Scenario: Approved host selects an enhanced engine
- **WHEN** an authorized source is explicitly configured to use a registered alternative HTTP engine
- **THEN** the transport invokes that engine through the same policy boundary and records the selected engine in diagnostics

#### Scenario: Requested engine is unavailable
- **WHEN** configuration selects an engine that is not installed, registered, or permitted for that source
- **THEN** the request fails closed with a configuration failure and does not silently select a more permissive engine

### Requirement: Host policy remains authoritative across engines
All registered request engines SHALL remain subject to the same host-scoped pacing, concurrency gate, request budget, retry classification, `Retry-After`, single-flight, exact-date cache isolation, cooldown, and half-open recovery contract. Engine-internal behavior MUST NOT create retries or upstream requests beyond that authoritative budget.

#### Scenario: Enhanced engine receives a recoverable failure
- **WHEN** an enhanced engine returns a connection failure, read failure, HTTP 408, HTTP 429, or HTTP 5xx result
- **THEN** the shared host policy decides whether another attempt is allowed and records all attempts against the same request budget

#### Scenario: Identical requests select the same engine
- **WHEN** concurrent identical requests resolve to the same engine, parameters, and requested date
- **THEN** they join one shared in-flight operation and do not emit duplicate upstream requests

#### Scenario: Host circuit is open
- **WHEN** a host is in cooldown and a request is configured for an enhanced engine
- **THEN** the request fails fast or proceeds to the existing provider fallback without bypassing cooldown through another engine

### Requirement: Enhanced engines do not bypass access controls
An alternative HTTP engine MUST NOT automatically reinterpret HTTP 401/403, authentication failure, CAPTCHA or interstitial challenge, denied provider permission, or unsupported requested date as recoverable evidence. Switching to browser automation, using challenge-solving behavior, or using a proxy requires an independently reviewed capability and explicit authorization; none is enabled by this change.

#### Scenario: Permission response is received
- **WHEN** any engine receives HTTP 401/403 or a provider-specific permission denial
- **THEN** the transport returns a non-retryable permission failure and does not escalate to a stealth, browser, or proxy-backed request

#### Scenario: Browser challenge is detected
- **WHEN** an engine detects a CAPTCHA, interstitial, or other access-control challenge
- **THEN** the response is classified as unavailable or challenged and is not stored as a successful provider response

#### Scenario: Enhanced engine is not explicitly enabled
- **WHEN** the optional enhanced-engine setting is absent or disabled
- **THEN** no alternative HTTP runtime is started and the default transport behavior remains unchanged

### Requirement: Transport diagnostics are engine-neutral and redacted
Every request engine SHALL expose normalized status, headers needed for policy decisions, response bytes or text, final URL, timings, and classified errors sufficient for provider validation and transport diagnostics, while credentials, cookies, proxy secrets, and challenge response bodies remain redacted from persisted evidence and logs.

#### Scenario: Provider validator consumes an enhanced response
- **WHEN** an enhanced engine successfully fetches an authorized provider response
- **THEN** the provider validator can inspect the engine-neutral response without importing the engine's native response type

#### Scenario: Enhanced request fails
- **WHEN** the engine returns a transport, permission, challenge, or timeout failure
- **THEN** diagnostics identify the engine and failure class without exposing sensitive request or session material

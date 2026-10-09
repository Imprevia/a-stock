## ADDED Requirements

### Requirement: Authenticated JSON POST requests remain isolated and redacted
The provider transport SHALL carry authorized JSON POST requests through the same host-scoped
policy gateway as other provider requests. Request identity SHALL use normalized endpoint
metadata, requested date, source id, a body digest, and an authentication-scope digest; it MUST
NOT contain the raw token or request body. Sensitive values found under JSON keys such as
`token`, `secret`, `password`, `cookie`, or `authorization` SHALL be excluded from diagnostics
and scrubbed from bounded provider error evidence even when echoed in a response. POST responses
MUST NOT enter the TTL cache unless a source explicitly declares them cache-safe.

#### Scenario: Two accounts issue otherwise identical POST requests
- **WHEN** requests share endpoint, API name, fields, parameters, and date but use different tokens
- **THEN** their authentication-scope digests and request identities differ without either token appearing in identities or diagnostics

#### Scenario: Identical authorized POST requests overlap
- **WHEN** identical Tushare requests for one account and exact date overlap
- **THEN** they may join one in-flight operation under the shared host budget while no persistent response cache is populated by default

#### Scenario: Provider error echoes a token
- **WHEN** a JSON error field includes all or part of a credential value submitted in the request body
- **THEN** persisted or returned diagnostics contain a redaction marker and never the credential value or raw request body

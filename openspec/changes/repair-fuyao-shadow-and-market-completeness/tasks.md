## 1. Contract and evidence

- [x] 1.1 Update breadth timestamp normalization and evidence fields; verify same-date second-level drift passes while cross-date pages fail.
- [x] 1.2 Add core shadow difference classification and bounded summaries; verify value mismatches remain `mismatch`.
- [x] 1.3 Define sectors enrichment capability and missing-field policy from documented Fuyao endpoints; verify no zero/code/name fabrication.

## 2. Implementation and integration

- [x] 2.1 Implement adapter/comparator changes and update redacted fixtures.
- [x] 2.2 Update collection metadata and fallback behavior without enabling formal Fuyao cutover.
- [x] 2.3 Add focused adapter, provider, shadow and collection tests.

## 3. Verification and rollout boundary

- [x] 3.1 Run offline tests, docs contract and OpenSpec strict validation.
- [x] 3.2 Run an isolated post-close real probe/shadow and retain the previously completed loopback PostgreSQL capability/shadow smoke evidence; no production DB/PVC/Kubernetes access.
- [x] 3.3 Update active plan with residual gaps; keep all formal Fuyao switches disabled unless separately approved.

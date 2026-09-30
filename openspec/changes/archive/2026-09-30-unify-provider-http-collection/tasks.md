# Tasks

## 1. Transport foundation

- [x] 1.1 Add shared provider HTTP transport with host policy, modern per-host UA, standard headers, timeout, retry classification, `Retry-After`, request budgets, and diagnostics; verify with transport unit tests.
- [x] 1.2 Add single-flight request coalescing, successful GET TTL cache, exact-date cache keys, and host cooldown/half-open probing; verify concurrency, cache, and circuit tests.

## 2. Provider migration

- [x] 2.1 Adapt Eastmoney compatibility client to the shared transport without changing existing limiter, error, or fallback contracts; verify existing Eastmoney retry and 403 tests.
- [x] 2.2 Migrate Tencent, Baidu, Sina, TDX package, and TDX name-enrichment requests to the shared transport; verify provider integration and fallback routing tests.

## 3. Documentation and operational contract

- [x] 3.1 Update architecture, runbook, product specification, status, and active execution plan with the transport boundary and operational checks; verify docs links and required plan fields.

## 4. Validation

- [x] 4.1 Run focused/full pytest, OpenSpec validation, and docs-contract gates; record evidence and remaining gaps in the active plan and task status.

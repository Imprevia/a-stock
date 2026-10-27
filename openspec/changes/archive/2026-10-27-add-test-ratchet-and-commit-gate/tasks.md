## 1. Plan and Documentation

- [x] 1.1 Create the active execution plan and index entry before implementation, with all required fields; verify docs-contract fast passes.
- [x] 1.2 Update AGENTS.md, runbook and repository mappings for gate layers, coverage scope, hook installation and bypass auditing; verify docs-contract full.

## 2. Hook Installation and Execution Context

- [x] 2.1 Add a read-only verification mode to scripts/install-hooks.py; test inactive/active hooks, missing files, executable handling and Windows resolution without modifying unrelated Git config.
- [x] 2.2 Implement staged-tree execution or fail closed on overlapping unstaged edits; test partial staging, renamed/deleted files and preserved index/stash contents in isolated temporary repositories.
- [x] 2.3 Preserve pre-push ref inputs and full docs-contract execution; test multiple refs, new branches and deletions without publishing anything.

## 3. Close Runtime Interface Gaps

- [x] 3.1 Add HTTP GET /api/health success assertions and verify actual dispatch is recorded.
- [x] 3.2 Add HTTP v2 breadth success and missing/insufficient-data tests; assert exact date, envelope and quality fields.
- [x] 3.3 Add HTTP v2 active-direction/workbench success and revision/conditional-header tests; assert applicable status codes and envelope fields.
- [x] 3.4 Verify every declared API/discovery method-and-path pair is exercised by passing tests; explicitly exclude frontend catch-all, static assets and framework documentation routes.

## 4. Coverage and Ratchet Measurement

- [x] 4.1 Add coverage>=7,<8 to requirements.txt without pytest-cov; verify a clean dependency install and direct coverage JSON reporting.
- [x] 4.2 Implement an opt-in pytest plugin recording actual request method, route template, response status and test outcome; test GET/PUT distinction, error-only observations, absent instrumentation and patch restoration.
- [x] 4.3 Collect sorted node IDs plus execution/skip outcomes; verify deleted, renamed and skipped tests are distinguishable and unexpected database-test skips block authoritative success.
- [x] 4.4 Measure src/ line coverage and compare per-file uncovered-statement ceilings; test increased uncovered counts, covered-code deletion, file removal, new-file candidate entries and aggregate-ratio reporting. Document that assertion weakening without execution changes is not guaranteed detectable.
- [x] 4.5 Implement explicit baseline generation at tests/baselines/test-ratchet.json with all three facts and sanitized environment/version metadata; verify ordinary checks never overwrite it or serialize credentials.
- [x] 4.6 Compare proposed baseline changes with the trusted parent/target baseline; test that raising uncovered ceilings or silently dropping inventory cannot conceal a regression, while documented rename reconciliation and stricter ceilings are reviewable.
- [x] 4.7 Generate the initial baseline only from a green CI-equivalent isolated PostgreSQL run and repeat it for determinism; inspect skip reasons and report environment mismatch as nonzero incomplete, not success. Do not use the exploratory local 83% as the authoritative baseline.

## 5. Fast and Intermediate Layers

- [x] 5.1 Implement change-to-test mapping with backend and frontend-specific fallbacks; test nested modules, shared helpers, changed tests, unmatched files and broad changes.
- [x] 5.2 Implement commit mode chaining docs-contract fast and selected tests; verify docs-only changes skip tests explicitly and failing selected tests block the commit.
- [x] 5.3 Implement push mode chaining docs-contract full, architecture checks, rule validation/coverage and expanded selected tests; verify all failures propagate and the full backend suite is not launched.
- [x] 5.4 Measure representative commit/push cases against advisory 30s/180s targets; record durations and warnings without silently replacing unfinished tests with success.

## 6. Single Authoritative CI Execution

- [x] 6.1 Implement CI mode launching coverage run -m pytest tests -q with the route plugin exactly once; reuse that run for test outcomes, operation coverage and line coverage. Verify no second plain pytest invocation occurs.
- [x] 6.2 Extend .github/workflows/trading-rules-pr.yml in place, preserving its display name, offline-rule-gate job identity, PostgreSQL image digest and test database configuration; verify rule/schema/golden/evidence/docs checks remain enforced.
- [x] 6.3 Add Node setup, lockfile-based frontend dependency installation and npm run test to the same workflow; verify frontend failures fail the existing required check and no sibling workflow duplicates the full suite.
- [x] 6.4 Verify database-backed tests execute with the isolated configured database and fail closed if required configuration disappears; allow existing explicit skips only in non-authoritative local runs and record reasons.
- [x] 6.5 Verify checks use fixtures and isolated test services, never real providers, production databases, deployment writes or scheduling operations; distinguish dependency-download setup from offline test execution.

## 7. Bypasses and Platform Verification

- [x] 7.1 Implement explicit emergency bypass with reason auditing at the correct Git lifecycle stage; test that pre-commit never trusts stale COMMIT_EDITMSG and that missing interpreter/tool blocks by default.
- [x] 7.2 Ensure CI ignores local skip markers/variables; test reported bypasses never appear as verified test passes.
- [x] 7.3 Verify interpreter/npm resolution and equivalent results on Windows/macOS/Linux using available platform tests; record any unavailable real-platform validation as a gap.

## 8. Activation and Acceptance

- [x] 8.1 Replace thin hook delegation rather than appending unreachable code after exec; preserve docs-contract checks and install/verify any audit hook. Validate in disposable repositories without committing or creating branches in the user's repository.
- [x] 8.2 In isolated fixtures, delete a test, remove an operation test and increase uncovered statements; verify each expected failure, plus successful unchanged-tree checks and missing-database fail-closed behavior.
- [x] 8.3 Run strict OpenSpec validation, full docs-contract and git diff checks; update the execution plan's Status, Completion Evidence, Remaining Gaps and Next Step with real baseline metadata and measured layer timings.

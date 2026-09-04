## 1. Planning and Documentation Contract

- [x] 1.1 Create `docs/exec-plans/active/complete-index-synchronization-assessment.md` with all required Stage, Status, Acceptance, Completion Evidence, Remaining Gaps, and Next Step fields, and register it in the active plan index before code changes.
- [x] 1.2 Update `docs/product-specs/market-environment-dashboard.md` to define the two-stage synchronization assessment, four documented relationship outcomes, confirmation statuses, additive API behavior, and desktop/mobile acceptance criteria.
- [x] 1.3 Update `docs/architecture.md` with the direction-pattern to breadth/trend/turnover confirmation flow and the exact previous-trading-day breadth snapshot dependency; update `docs/runbooks.md` with read-only lookup, missing-snapshot, rebuild, and debugging behavior.

## 2. Calculation Model and Schema

- [x] 2.1 Add typed schema models for `synchronizationAssessment`, its closed top-level and dimension statuses, nullable numeric inputs, stable conclusion code, confidence, evidence, risks, and optional placement under `Summary` without changing existing `syncPattern` fields.
- [x] 2.2 Implement pure breadth, trend, and turnover confirmation calculations using the existing 55/45 percent breadth boundaries, MA20 majority boundary, 5-day turnover ratios, and documented volume-backed decline condition; preserve nulls and explicit insufficiency reasons.
- [x] 2.3 Implement the pattern-specific assessment mapping for synchronized rally, weight shelter, growth leadership, broad weakness, and undetermined divergence, including confirmed, unconfirmed, contradicted, and insufficient outcomes and the five-of-five weakness evidence flag.
- [x] 2.4 Add table-driven calculation tests covering all documented confirmed cases plus contradictory, mixed, and missing-input variants; verify unsupported sector attribution is never generated.

## 3. Previous-Day Breadth and Service Integration

- [x] 3.1 Derive the previous trading date from valid core index history and add an exact-date breadth snapshot read that never searches older dates or invokes a provider when the required snapshot is missing.
- [x] 3.2 Assemble `summary.synchronizationAssessment` from the existing pattern and same-date inputs plus optional exact previous-day breadth, return dated deltas when available, and cap confidence when comparison evidence is absent.
- [x] 3.3 Make the synchronization assessment the authoritative source for the market-strength explanation and risk justification while preserving the six-combination-derived stage, capital-acceptance logic, existing matrix contract, and current trading-rule inputs.
- [x] 3.4 Extend service, API, snapshot-store, and materialized-aggregate tests to verify exact previous-date use, rejection of older substitutes, zero provider calls on normal GET paths, additive schema compatibility, and rebuild behavior.

## 4. Section 01 Dashboard

- [x] 4.1 Extend frontend TypeScript contracts for the assessment and all three confirmation dimensions without weakening existing null and missing-data handling.
- [x] 4.2 Add a dedicated synchronization assessment band before the four-question and six-combination matrix section, showing the raw pattern, confirmation status, conclusion, confidence, breadth/trend/turnover values, evidence, and risk notices.
- [x] 4.3 Add responsive styles with stable dimension sizing, vertical mobile stacking, no nested cards, no page-level horizontal overflow, and no visible text below the repository's 14px minimum.
- [x] 4.4 Add Vue tests for confirmed synchronized rally, contradicted index-only rally, confirmed weight shelter, unconfirmed and confirmed growth leadership, confirmed systemic decline, and missing previous-day breadth; assert the contradicting or insufficient dimension remains visible.

## 5. Verification and Completion Evidence

- [x] 5.1 Run focused and full Python tests, including deterministic regression checks proving the existing five-state thresholds, six combinations, 49 executable rules, aggregate members, scores, and golden traces are unchanged.
- [x] 5.2 Run frontend tests and production build, then perform desktop and 390px browser QA for Section 01 data loading, synchronization evidence, contradictory and insufficient states, text fit, and overflow.
- [x] 5.3 Run `python scripts/check-docs-contract.py --mode=full` and `openspec validate complete-index-synchronization-assessment --strict`, recording command results and any environment-limited checks in the active plan.
- [x] 5.4 Update `docs/status.md` and the active plan Status, Completion Evidence, Remaining Gaps, and Next Step with the final implementation and validation results; leave empirical thresholds marked as needing backtest.

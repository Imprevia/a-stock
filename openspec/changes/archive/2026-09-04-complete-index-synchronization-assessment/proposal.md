## Why

The current Section 01 implementation classifies five-index direction into five labels, but it does not consistently turn those labels into the business conclusions documented in the trading-system source. Weight shelter is collapsed into generic divergence, growth leadership is treated like a synchronized rally, and broad weakness can trigger risk control without confirming turnover expansion, moving-average damage, or worsening market breadth.

## What Changes

- Add a market-level synchronization assessment that keeps the observed five-index direction pattern separate from its breadth, trend-position, and turnover confirmations.
- Produce distinct interpretations for synchronized rally, weight shelter, growth leadership, broad weakness, and undetermined divergence instead of reducing them to generic strong/weak/divergent text.
- Confirm or contradict the direction pattern with current market breadth, prior-trading-day breadth change when available, the share of indices above or below MA20, index combination evidence, turnover ratios, and volume-price states.
- Reserve conclusions such as "weight shelter with weak individual stocks" and "systemic risk decline" for cases whose required confirming evidence is present; otherwise emit an unconfirmed, contradicted, or insufficient result.
- Expose the assessment as additive API data with a stable machine-readable status, conclusion, confidence, evidence, and risk notices, while preserving the existing `syncPattern` contract.
- Add a dedicated Section 01 presentation for index synchronization and its confirmation chain so users can see why the market was classified, not only the final label.
- Add backend and frontend scenario coverage for all four documented market relationships, including missing prior-day breadth and conflicting evidence.

No existing five-state thresholds, six index-combination thresholds, trading-rule IDs, aggregate members, or scoring weights are changed by this proposal.

## Capabilities

### New Capabilities

- `index-synchronization-assessment`: Contextual interpretation of five-index synchronization using market breadth, trend position, and turnover confirmation, with auditable API and dashboard output.

### Modified Capabilities

None.

## Impact

- **Backend:** `src/market_environment/calculations.py`, `service.py`, and `schemas.py` gain the contextual assessment calculation and additive response fields; exact-date snapshot assembly may read prior-trading-day breadth when available without calling providers from normal GET paths.
- **Frontend:** `apps/market-environment-dashboard/src/App.vue` and `types.ts` gain a synchronization assessment section showing the direction pattern, confirmation dimensions, conclusion, confidence, and evidence.
- **Tests:** calculation, service/API, snapshot, and Vue tests gain scenario matrices for synchronized rally, weight shelter, growth leadership, broad weakness, contradictory evidence, and missing confirmation data.
- **Documentation:** the market-environment product specification, architecture, runbook, repository status, and active execution plan must describe the new assessment semantics and prior-day snapshot dependency.
- **Compatibility:** API changes are additive; existing `summary.syncPattern`, index analyses, six-combination matrix, and trading-rule evaluation remain available and retain their existing field meanings.
- **Dependencies:** no new third-party dependency and no new real-time provider request path.

## 1. Governance and Contracts

- [x] 1.1 Create and index the active execution plan for the rule engineering change
- [x] 1.2 Add the product specification and update architecture, runbook, repository guide, status, and trading-system indexes
- [x] 1.3 Add YAML and JSON Schema dependencies and create the rule, event, snapshot, and evidence schemas

## 2. Rule Registry

- [x] 2.1 Implement typed rule models, closed-schema loading, evaluator lookup, duplicate detection, and lifecycle validation
- [x] 2.2 Generate the 327-rule coverage inventory from quantified documentation with bidirectional document checks
- [x] 2.3 Register all 46 chapter 01 rules as versioned YAML with explicit threshold provenance and document references

## 3. Data and Evaluation

- [x] 3.1 Implement canonical snapshot models, structured event validation, canonical JSON, and SHA-256 hashing
- [x] 3.2 Implement deterministic evaluator primitives, missing-data handling, score bands, confidence, veto precedence, and trace output
- [x] 3.3 Implement chapter 01 aggregation and environment classification over exactly 46 rule traces
- [x] 3.4 Implement provider quality records, fallback contracts, and the serial Eastmoney limiter without coupling network access to evaluation

## 4. Evidence and Backtest

- [x] 4.1 Implement manifest-based evidence bundle creation and tamper verification
- [x] 4.2 Implement chronological replay, coverage checks, in-sample/out-of-sample partitioning, costs, confidence intervals, and validation evidence checks
- [x] 4.3 Add tracked validation and monthly evidence summary templates

## 5. CLI and Automation

- [x] 5.1 Implement the unified rules, snapshot, evaluate, backtest, evidence, and docs CLI commands
- [x] 5.2 Add an offline pull request workflow with fixture, golden, pytest, synchronization, and docs-contract gates
- [x] 5.3 Add a scheduled and manually dispatchable after-market workflow that uploads evidence on success, degradation, or insufficient data

## 6. Verification and Completion

- [x] 6.1 Add schema, registry, snapshot, evaluator, golden, provider, evidence, backtest, CLI, and failure-mode tests
- [x] 6.2 Run the full test suite, CLI replay, OpenSpec validation, and full docs contract; resolve failures
- [x] 6.3 Record completion evidence and remaining gaps, archive the exec plan, and synchronize the active plan index

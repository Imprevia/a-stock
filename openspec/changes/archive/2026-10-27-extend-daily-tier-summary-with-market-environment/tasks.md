## 1. Execution Plan And Documentation Contract

- [x] 1.1 Create and index `docs/exec-plans/active/extend-daily-tier-summary-with-market-environment.md` with Stage, Status, Acceptance, Completion Evidence, Remaining Gaps, and Next Step; verify `.venv/bin/python scripts/check-docs-contract.py --mode=fast` recognizes the plan before implementation edits.
- [x] 1.2 Update `docs/repository-guide.md` and any affected Skill-facing documentation mapping to include the combined environment read contract and dual verification output; verify documented paths and safety boundaries match the implementation scope.

## 2. Skill Contract And References

- [x] 2.1 Update `.agents/skills/a-stock-daily-tier-summary/SKILL.md` with the confirmed full line order, named index/MA20 requirements, same-date rule, and separate tier/environment verification namespaces; verify no `___` placeholder, trade recommendation, or score contract remains.
- [x] 2.2 Extend `references/data-contract.md` with v2 overview/indices/breadth reads, one pinned current-session revision, cross-resource date checks, normalized environment fixture shape, and local failure behavior; verify every new read remains GET-only and provider-free.
- [x] 2.3 Extend `references/methodology.md` with canonical evidence precedence, breadth consistency/ divergence, Section 01 environment categories, confidence meaning, and A1-A5 environment verification selection; verify the thresholds match the existing index documents and are marked `needs-backtest` where applicable.

## 3. Exact-Date Environment Acquisition

- [x] 3.1 Add normalized market-environment models and structured JSON fields for named direction groups, named MA20 groups, breadth, turnover, canonical pattern/assessment, confidence, gaps, and environment verification; verify serialization contains the current date and revision but no raw response or credentials.
- [x] 3.2 Extend the local v2 adapter to read overview first and pin its revision across indices, breadth, limits, and all current limits pool pages while preserving the previous session's independent limits revision; verify a transport test asserts every current request carries one revision and uses only approved GET paths.
- [x] 3.3 Add fail-closed validation for current-session date mismatch, revision mismatch/409, duplicate or missing expected index identities, and conflicting non-null canonical evidence; verify each case returns an explicit insufficient error instead of a mixed-date conclusion.
- [x] 3.4 Extend fixture input with a compact normalized environment section and quality metadata; verify existing limits-only fixtures either remain backward compatible with an explicit environment-insufficient result or are migrated deterministically without network access.

## 4. Environment Interpretation And Verification

- [x] 4.1 Implement deterministic named direction and MA20 grouping in canonical index order, including flat and data-insufficient groups; verify one-up/four-down, all-below, mixed-position, equality, and missing-value cases.
- [x] 4.2 Reuse canonical synchronization assessment and breadth labels, cross-check raw counts, and derive consistency or divergence only when the canonical field is absent; verify negative breadth with mostly falling indices is consistent and negative breadth with a positive pattern is divergent.
- [x] 4.3 Implement the documented Section 01 environment category and confidence mapping without upgrading an undetermined pattern to broad weakness unless the four-of-five direction gate is met; verify the discovery-shaped case yields qualified weak-divergence observation wording and low confidence.
- [x] 4.4 Implement one environment next-session verification using A1-A5 priority while leaving the tier `previousPlan` and `nextSessionVerification` behavior unchanged; verify breadth's paired fields count as one concept and insufficient inputs produce a recovery check rather than fabricated direction thresholds.

## 5. Full Review Rendering

- [x] 5.1 Expand `render_summary` to emit the confirmed line order exactly once: named indices, named MA20 groups, breadth/turnover facts, width relation, previous verification, evidence-rich tier conclusions, risk/structure, tier verification, environment conclusion, confidence, and environment verification; verify a complete synthetic card contains no placeholder text.
- [x] 5.2 Keep tier conclusions auditable by rendering frozen-sample outcomes, failed-sample repair numerator/denominator, and relevant pool changes, while refusing to treat aggregate pool totals as tier facts when streak data is missing; verify partial tier evidence only degrades affected lines.
- [x] 5.3 Add a discovery-shaped synthetic fixture with one rising/four falling indices, all five below MA20, negative breadth, neutral turnover confirmation, failed high-tier prior verification, and low-tier expansion; verify the card names every index and contains distinct tier and environment verification lines.

## 6. Offline Behavioral Coverage And Completion Gates

- [x] 6.1 Add focused pytest cases for same-date/revision enforcement, canonical evidence precedence, named group rendering, local missing fields, cross-date refusal, environment classification, confidence, and dual verification namespaces; verify the complete module passes without network access.
- [x] 6.2 Run the bundled Skill quick validator, focused pytest, `openspec validate extend-daily-tier-summary-with-market-environment --strict`, and `git diff --check`; record exact results in the active plan Completion Evidence.
- [x] 6.3 Run `.venv/bin/python scripts/check-docs-contract.py --mode=full`, update the active plan Status, Completion Evidence, Remaining Gaps, and Next Step, and verify no API, database, provider collection, deployment, schedule, credential, or production snapshot was modified.

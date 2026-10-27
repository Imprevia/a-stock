## 1. Execution Planning And Documentation Baseline

- [x] 1.1 Create and index `docs/exec-plans/active/add-a-stock-daily-tier-summary-skill.md` with all required status, acceptance, evidence, gaps, and next-step fields; verify `python scripts/check-docs-contract.py --mode=fast` recognizes the active plan before implementation edits.
- [x] 1.2 Update `docs/repository-guide.md` with ownership and safety boundaries for repo-local Agent skills and their tests, and verify the documented paths match the files planned by this change.

## 2. Skill Package And Domain References

- [x] 2.1 Create `.agents/skills/a-stock-daily-tier-summary/SKILL.md` with discriminating frontmatter, local-data-first orchestration, explicit external fallback boundaries, fixed Chinese output, and previous-plan verification behavior; verify the bundled `quick_validate.py` accepts the Skill directory.
- [x] 2.2 Add `references/data-contract.md` documenting exact-date inputs, pagination/revision pinning, normalized security identity, `streak_days`/`lbc` precedence, forbidden `zttj.days` tier use, quality propagation, and nullable denominator behavior; verify every reference is linked from `SKILL.md` only where needed.
- [x] 2.3 Add `references/methodology.md` mapping observable facts to the five descriptive structure labels and one-layer next-session verification rules while preserving `needs-backtest`; verify it contains no automatic trading advice or unvalidated score contract.

## 3. Deterministic Analysis Script

- [x] 3.1 Implement normalized session, pool, security identity, source-date evidence, and quality models in `scripts/analyze_tier_summary.py`; verify synthetic inputs deduplicate by exchange-qualified identity and reject conflicting rows deterministically.
- [x] 3.2 Implement exact-date local v2 reads with complete cursor pagination and per-date revision pinning, plus fixture/JSON input mode; verify tests prove local reads issue no provider-triggering or write requests.
- [x] 3.3 Implement the explicit Eastmoney read-only fallback with bounded timeouts, request-date and `qdate` evidence, normalized `lbc`, and fail-closed date handling; verify a request-date-only fixture is degraded and an explicit date contradiction is insufficient.
- [x] 3.4 Implement frozen previous-session tier outcomes, current tier counts, pool deltas, and nullable failed-sample repair; verify `lbc=2` with `zttj.days=8` remains middle tier and a zero repair denominator does not produce `0%`.
- [x] 3.5 Implement optional structured previous-plan evaluation with confirmed, invalidated, inconclusive, conflicting, and unavailable states; verify each state cites the original condition and observed value without changing thresholds after the fact.
- [x] 3.6 Emit a stable structured JSON result containing dates, sources, quality, tier outcomes, repair evidence, verification result, and facts needed for prose rendering; verify serialization contains no credentials, raw provider response, or runtime snapshot payload.

## 4. Offline Behavioral Coverage

- [x] 4.1 Add compact synthetic fixtures for duplicates, conflicting identities, field precedence, partial tier coverage, exact-date mismatch, weekend/holiday resolution, zero denominator, and all previous-plan states; verify fixtures contain no real market snapshot or secret.
- [x] 4.2 Add focused pytest coverage for normalization, cross-session arithmetic, repair calculation, quality propagation, source fallback, and date resolution; verify the new test module passes without network access.
- [x] 4.3 Add a fixture-based end-to-end Skill exercise that validates dates, counts, ratios, one structure label, and one next-session layer without matching exact prose; verify the fixed four-part Chinese response can be produced from the structured result.

## 5. Completion Gates

- [x] 5.1 Run the Skill quick validator, focused pytest suite, `openspec validate add-a-stock-daily-tier-summary-skill --strict`, and `git diff --check`; record command results in the active plan's Completion Evidence.
- [x] 5.2 Run `python scripts/check-docs-contract.py --mode=full`, update the active plan's Status, Completion Evidence, Remaining Gaps, and Next Step, and verify no production collection, database write, schedule, credential, or real snapshot was changed.

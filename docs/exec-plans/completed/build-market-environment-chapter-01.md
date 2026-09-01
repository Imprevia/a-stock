## Stage

Chapter 01 market-environment dashboard extension.

## Status

completed

## Acceptance

- The dashboard has a first-level navigation item for `如何判断市场环境` and second-level links for documents 01 through 09.
- The page presents rule-linked market evidence for index structure, breadth, limit-up/limit-down ecology, tier risk, sector/active direction, event verification, and final classification.
- Real-data adapters prefer Tencent/mootdx for prices and follow the a-stock-data endpoint and rate-limit conventions for unique Eastmoney datasets.
- Missing or unavailable datasets remain `null`/`insufficient` with provider warnings; no synthetic zero values are introduced.
- Existing API consumers, tests, production build, and docs-contract remain valid.

## Completion Evidence

- `.venv\Scripts\python.exe -m pytest tests -q` -> `38 passed`.
- `npm run build --prefix apps/market-environment-dashboard` -> Vite production build passed.
- `.venv\Scripts\python.exe scripts/check-docs-contract.py --mode=full` -> passed before final documentation archive.
- Playwright desktop `1440x900` and mobile `390x844` screenshots showed nonblank charts and no incoherent overlap.
- Automated browser interaction verified 9 document links, desktop documents 01/02/09, the mobile drawer/document 05, zero page-level mobile overflow, and no browser console errors.

## Remaining Gaps

- Historical percentile calibration and 500-750 trading-day evidence are not part of this slice.
- Event/policy inputs remain explicitly unverified unless an official or traceable source is supplied.
- High/mid/low tier loss-effect evidence remains insufficient until an independently traceable sample is available.
- The page can show provider-backed current metrics, but it does not claim that empirical thresholds are validated.

## Next Step

Create a separate active plan for tiered loss-effect data or historical threshold calibration before extending this chapter again.

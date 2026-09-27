# 修复 TDX 市场广度证券宇宙

## Stage

Stage 2 — TDX 普通 A 股分类、生产部署与精确日期重采集完成

## Status

production-repair-complete

## Acceptance

- TDX 盘后包在 `breadth` 和 TDX 派生 `activeDirection` 使用前，按请求日期适用的版本化代码规则只保留可证明的普通 A 股。
- 上海主板/科创板、深圳主板/创业板和北京证券交易所普通股票均有明确规则；基金、债券、指数、权证、B 股、存托凭证及未知身份默认排除。
- 质量对象记录策略版本、过滤前/保留/排除/未分类数量、按市场保留数量和排除原因；三类广度计数与过滤后有效样本一致。
- 过滤后样本或市场覆盖不足时不写入伪造成功快照；同日期失败继续使用 `failed-retained` / `failed-missing`，普通 GET 不触发修复。
- 公开 `breadth` 计数字段、`activeDirection` Top-N 字段、Eastmoney 主链和现有快照 checksum/lease 语义保持兼容。
- 2026-09-23、2026-09-24 等错误日期按明确授权原日期重采集，不执行直接 payload 修改、跨日期回填或 PVC 操作。

## Completion Evidence

- [x] OpenSpec `fix-tdx-breadth-stock-universe` implementation tasks 1.1–6.4 completed after explicit real-provider and production-write authorization.
- [x] Focused and full offline pytest、前端测试/构建、docs sync-check、docs-contract full completed.
- [x] Fixed fixtures prove mixed-security filtering, 920 boundary handling, exact-date retention, failed-retained/failed-missing and provider-free reads.
- [x] Focused TDX suite after expanded non-stock ranges: `.venv/bin/python -m pytest tests/test_market_environment_tdx_daily.py -q` -> `39 passed`.
- [x] Market environment regression slice: `.venv/bin/python -m pytest tests/test_market_environment_tdx_daily.py tests/test_market_environment_providers.py tests/test_market_environment_collection.py tests/test_market_environment_service.py tests/test_market_environment_api.py tests/test_market_environment_snapshot_store.py -q` -> `142 passed, 2 warnings`.
- [x] Post-change collection/TDX slice after explicit historical `--force` repair path: `.venv/bin/python -m pytest tests/test_market_environment_collection.py tests/test_market_environment_tdx_daily.py -q` -> `64 passed`.
- [x] Full backend suite: `.venv/bin/python -m pytest tests -q` -> `695 passed, 3 skipped, 2 warnings`.
- [x] Dashboard tests: `npm run test --prefix apps/market-environment-dashboard` -> `20 files passed, 122 tests passed`.
- [x] Dashboard production build: `npm run build --prefix apps/market-environment-dashboard` -> built successfully; Vite emitted only the existing chunk-size warning.
- [x] Trading docs sync-check: `.venv/bin/python -m src.trading_system.cli docs sync-check` -> `{"documentedRules": 330, "executableRules": 49}`.
- [x] Docs contract full: `.venv/bin/python scripts/check-docs-contract.py --mode=full` -> `docs-contract: 通过（代码 20 / 文档 7 / plan 3）`.
- [x] OpenSpec strict validation: `openspec validate fix-tdx-breadth-stock-universe --strict --no-interactive` -> valid.
- [x] Whitespace check: `git diff --check` -> passed.
- [x] Read-only real probes with `--allow-real` for `2026-09-23` and `2026-09-24` wrote only redacted reports under `.artifacts/market-environment/`; both reported `sourceDate=requestedDate`, policy `tdx-stock-universe-v1`, `unclassified=0`, and retained counts `5560` / `5561`.
- [x] Controlled deployment: active CronJob was first handled through the reviewed `--disable-schedule` entry (first pass fail-safe suspended it; second pass removed the retained exact resource and proved absent); service deployment completed at Helm revision `60`, Deployment rollout ready, image `localhost/a-stock-market-environment:20260925-010233-a690d44`, imported containerd digest `sha256:c94273dda0deb5e149089364e96711f5b7ab2c3006890b2723ae7229aa8ebb54`, `/api/health` returned `{"status":"ok"}`, and CronJob remained absent.
- [x] Production exact-date repair `2026-09-23`: run `2895a951349f42fa8762d0449f012ee8` ended `partial`; `breadth` task `4df7b886392745ba84f411071e3a7ce8` was `success` with `5560` observations, `activeDirection` task `4c87b06bd82343debee2bcbd8f358ff0` was `partial` with 30 observations and `tdx-daily-package-derived`.
- [x] Production exact-date repair `2026-09-24`: run `c9e8efde71c445d79832058e8279000a` ended `partial`; `breadth` task `8fe42cdd1d6c447cb9db3bf43afb7189` was `success` with `5561` observations, `activeDirection` task `61c5617b3abd43398ad27b2281c00159` was `partial` with 30 observations and `tdx-daily-package-derived`.
- [x] Post-repair production storage evidence: `breadth` checksums are `59c7255e81889962621c51911cebc4dcbea3030f9d7935e25cf89ffa562927ee` / `e9a44f2e75e1189f848cb037248839ff02902e397dfb50c69a0fa43dc5b4c1e7`; `activeDirection` checksums are `434e3c421f292e3eacb6d3f8550eb44a0bf203e6a152dd05014567ee0b55b37c` / `2d44b3d8488054f9e75c7985a51eecf771fdac50acc37c28282b36d799460441`; both dates have rebuilt aggregate checksums and no schema validation error.
- [x] Post-repair aggregate/API evidence: `2026-09-23` breadth `advance/decline/flat/valid=1891/3562/107/5560`; `2026-09-24` `1120/4304/137/5561`; both dates expose policy `tdx-stock-universe-v1`, raw counts `51921` / `51891`, retained counts `5560` / `5561`, excluded counts `46361` / `46330`, unclassified `0`, and retained market counts `sh/sz/bj=2319/2895/346` and `2319/2895/347`.
- [x] Explicit historical repair path: `snapshots refresh --force` is the only CLI route that opts into historical latest-only collection; ordinary API collection, scheduled refresh, and direct `CollectionCoordinator` calls still reject historical `breadth`/`activeDirection`.

## Remaining Gaps

- 生产 Eastmoney 主/延迟端点仍不可用，因此两个日期的 `breadth` 使用 TDX fallback，`activeDirection` 使用 `fallback-derived`；这属于已记录的降级质量，不是未审计成功。
- TDX 派生 `activeDirection` 仍只有当日成交额/涨跌幅/收盘位置事实，20 日放量、超额收益、连续 2 日确认和完整行业映射继续保持未接入/不足。
- 定时 CronJob 当前按 fail-closed 规则保持 absent；如需恢复调度，必须另行走受控 `--release-suspended` / `--activate-schedule` 流程。

## Next Step

保持生产 GET provider-free，并在后续盘后窗口观察新日期；如需重新启用定时采集，先完成独立的 suspended release/canary 审核，不在本 change 中裸激活 CronJob。

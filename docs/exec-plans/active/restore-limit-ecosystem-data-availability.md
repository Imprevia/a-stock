# 恢复涨跌停生态数据可用性执行计划

## Stage（阶段）

Stage 1 — 扶摇主源接入、双源集合、PostgreSQL 事实扩展、基础晋级/历史、第 03/04 页和隔离验证。

## Status（状态）

`completed-with-insufficient-provider-evidence` · 代码、文档、离线测试、隔离 PostgreSQL 六日 smoke 和部署清单验证已完成；真实 provider 的高级严格字段仍按设计保持 partial/degraded，未执行生产写入。

## Scope（范围）

- 修复第 03 页涨停、跌停、炸板、晋级、梯队、五日历史和股票明细的数据可用性。
- 修复第 04 页读取不存在 `tierRisk` 导致永久数据不足的问题。
- 以扶摇为主源、东方财富为降级/交叉核对，基础集合和高级分层独立表达质量。
- 交付代码、文档、离线测试和隔离 PostgreSQL smoke；不部署生产、不写生产库、不创建生产 Secret。

## Acceptance（验收）

- 已确认交易日的三类池完整分页并按规范身份合并；显式空池为 0，非交易日或不完整分页不伪造 0。
- 基础晋级只依赖相邻交易日完整涨停集合和身份，高级属性缺失不阻断晋级、梯队与短期趋势。
- 最近 6 个交易日可显式回填并形成最近 5 个带晋级率的历史点；60/250 日覆盖缺口真实显示。
- limits API 返回四组证券明细，第 03 页可搜索/分页，第 04 页读取真实分层/修复证据。
- 日期切换和全局刷新自动重载当前 limits section，旧请求不覆盖新日期。
- V1 默认关闭，密钥只从独立 Secret 注入；普通 GET provider-free。
- 后端、前端、OpenSpec、规则、部署和 docs-contract 门禁通过。

## Completion Evidence（完成证据）

- 后端定向及全量 pytest：`pytest tests -q` → **620 passed, 3 skipped** in 196.46s；定向 `test_market_environment_fuyao.py` 27 passed，`test_market_environment_providers.py` 23 passed，`test_market_environment_limit_promotion.py` 17 passed，`test_market_environment_limit_facts.py` 21 passed（含 0001→0002 加法升级、fresh bootstrap 校验、checksum/lease/CAS 与旧五字段兼容），`test_market_environment_database.py` 9 passed/3 skipped（postgres-only 跳过），`test_market_environment_limit_contract.py` 42 passed（明细行、非法比例与旧字段兼容）。
- 前端：`npm run test` 20 文件 / **121 passed**，`DashboardLayout.section-refresh.test.ts` 4 passed 验证日期切换后重载 `limits`，`limits-page.test.ts` 7 passed 验证搜索/分页/行级 warning，`Document04TierRiskPage.test.ts` 验证 risk_tier/failure-repair；`npm run build` clean，2187 modules transformed，dist 1.28MB。
- 规则与文档门禁：`rules validate` 49 rules OK，`rules coverage` 330 documented / 49 executable OK，`docs sync-check` OK，`openspec validate restore-limit-ecosystem-data-availability --strict` valid，`check-docs-contract.py --mode=full` 通过（代码 26 / 文档 8 / plan 2），`git diff --check` clean。
- 部署与 Secret：`helm lint deploy/helm/a-stock` 0 failed；`helm template` 渲染独立 Secret `a-stock-market-provider` 注入 `MARKET_ENVIRONMENT_FUYAO_API_KEY`；复用 database secret 时模板渲染即 fail；`test_deployment_manifests.py` 4 fuyao/limits 用例 passed；密钥未出现在 values.yaml、API、日志或仓库文件。
- 隔离 PostgreSQL smoke（2026-09-21）：使用 Podman 临时 PostgreSQL 16.4 与一次性进程环境 Secret，执行 `--as-of 2026-09-11 --dataset limits --history-sessions 6 --force`，CLI 返回 `partial`（六日均成功写入基础事实，但严格 enrichment 字段缺失按契约降级）。实际落库日期为 `2026-09-04、09-07、09-08、09-09、09-10、09-11`；六日三类池均有事实，目标日 `09-11` 为涨停 40、跌停 21、炸板 18，事实行 79，来源 `fuyao+eastmoney`，membership/streak 完整，质量 `ok`。
- 同一隔离库的基础晋级点：`09-07` 13/39 = 0.3333、`09-08` 18/93 = 0.1935、`09-09` 15/73 = 0.2055、`09-10` 9/48 = 0.1875、`09-11` 7/35 = 0.2000；目标日四组明细均非空：`limitUp=40`、`limitDown=21`、`failedLimitUp=18`、`promoted=7`。晋级 quality 因双源并集差异为 `degraded`，比例均满足分子不大于分母。
- 失败边界：以 `2026-09-18` 为目标的另一组六日尝试在 `09-14` 因扶摇返回行无法通过标准证券身份校验而 `failed-missing`，其余日期保留成功/partial 快照，整体返回 `partial`；未将该日伪造成空池或成功。临时 PostgreSQL 容器已停止，未访问生产数据库。

## Remaining Gaps（剩余缺口）

- 扶摇未公开长期历史保留期，因此只承诺本次验证通过的最近 6 个交易日；缺失日期不替换其他日期。
- 行业板块和未充分证明的制度分层继续保持 `insufficient`（`provider-missing-sector`），不按代码或名称猜测。
- 生产部署、生产 Secret 注入与生产回填不在授权范围内。
- **凭据安全**：聊天中提供的两个 `sk-fuyao-*` 密钥已视作泄露，验证后必须轮换；本仓库与 chart 未持久化任何密钥。

## Next Step（下一步）

1. 在扶摇控制台轮换当前聊天泄露的 `sk-fuyao-*` 密钥，确认新旧 Secret 仅由 `MARKET_ENVIRONMENT_FUYAO_API_KEY` 注入，不进入 values.yaml/API 响应/日志。
2. 归档已完成的 OpenSpec change：`openspec archive restore-limit-ecosystem-data-availability --change-name restore-limit-ecosystem-data-availability`；归档前保留本计划中的 partial/degraded provider 证据和失败边界。

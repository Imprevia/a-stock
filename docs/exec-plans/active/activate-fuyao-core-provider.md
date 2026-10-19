# 启用 Fuyao Core 正式首选源执行计划

## Stage（阶段）

Stage 3 — task 6.5 same-image core-enabled 发布已完成；等待 task 6.6 单次盘后 core-only 采集的独立授权。

## Status（状态）

`formal-core-enabled-awaiting-single-collection-authorization`（2026-10-19：生产已以同镜像、无 hooks 配置发布启用 formal Fuyao core，shadow 仍关闭；尚未调用 provider 或执行 core-only 采集）

## Scope（范围）

- 将 Fuyao `fuyao-market-v2` 作为五个核心指数的正式第一数据源；单指数失败时继续按 `mootdx -> 百度 -> 新浪 -> 腾讯 -> 东方财富` 降级。
- `core.shadowEnabled=false`：不建设 shadow、不生成跨 provider 对账报告、不要求连续多日一致性比较。
- 正式启用前必须存在精确匹配、脱敏、checksum-valid 且状态为 `eligible` 的 Fuyao core capability report；报告只验证 Fuyao 自身端点、身份、OHLC/直接成交额、精确日期、至少 280 根历史、权限和有界请求预算。
- 保留当前日期腾讯独立报价校验、逐指数失败隔离、同日留存、跨日期拒绝、真实来源和质量状态等既有安全契约。
- 使用同镜像、无 hook、完整 core-off/core-enabled 配置；两者都固定 revision v2、shadow false，唯一允许的启用差异为 `MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED: 0 -> 1`。
- 启用后只允许在另行授权后执行一次盘后 core-only 采集；不自动重试或启动连续观察。部分指数回退时，运行结果仍可用，但 rollout acceptance 标记为 partial。
- 不改变公开 API、数据库 schema、交易规则、调度所有权、其他数据集、Secret/PVC/Service 或普通 GET 的 provider-free 边界。

## Acceptance（验收）

- OpenSpec strict 校验通过，delta spec 明确 Fuyao 正式首选、无 shadow、自包含 capability evidence、逐指数降级和可逆配置发布。
- 离线测试证明启用后每个指数的顺序为 `Fuyao -> mootdx -> 百度 -> 新浪 -> 腾讯 -> 东方财富`，Fuyao 成功保留 v2 与直接成交额证据，失败回退保留真实来源及 Fuyao 警告。
- capability policy 对 endpoint、五个规范指数、完整 OHLC/直接成交额、精确日期、至少 280 根、权限、请求预算、checksum 和 redaction fail closed；不依赖其他 provider 数值、shadow 状态、容差或多日对账。
- reviewed core-off/core-enabled 完整 Helm renders 使用同一镜像、同一资源集合，且唯一 off/on 语义差异为 `MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED: 0 -> 1`；两者 shadow 均关闭。
- Helm render 不包含 application-owned CronJob/Job；Secret 只引用不渲染，Service、PVC、数据库、调度和其他数据集保持不变。
- 真实生产 preflight、Fuyao probe、capability promotion、core-off 收敛、core-enabled 部署、core-only 采集和回滚必须分别获得明确授权。
- 经授权的单次 core-only 采集若五个指数全部来自 Fuyao，则验收为 full；若发生逐指数回退，则保留降级证据并标记 partial，不自动追加采集或对账。

## Completion Evidence（完成证据）

- 已创建 OpenSpec change：`openspec/changes/activate-fuyao-core-provider/`。
- 已完成 `proposal.md`：限定 Fuyao v2 正式首选、既有逐指数 fallback、无 shadow/对账以及独立授权边界。
- 已完成 `specs/market-data-collection-management/spec.md`：新增正式首选、逐指数降级、自包含 capability approval 和配置可逆四项 requirement。
- 已完成 `design.md`：确定 typed acquisition 复用、core capability policy、fresh report、单行 promotion、paired profiles、单次 core-only 验收和配置回滚。
- 已完成 `tasks.md`：覆盖离线实现、文档和确定性验证，并将所有真实 provider 与生产操作拆成分别授权的任务。
- 规划阶段未调用真实 Fuyao、未读取或修改 Secret、未连接生产数据库、未执行 Helm/kubectl 写操作、未触发市场数据采集。
- 规划校验：`openspec status --change activate-fuyao-core-provider` 显示 `4/4 artifacts complete`；`openspec validate activate-fuyao-core-provider --strict` 通过。
- 文档门禁：`python3 scripts/check-docs-contract.py --mode=full` 通过（代码 0 / 文档 3 / plan 2）。
- `git diff --check` 通过。
- `src/market_environment/infrastructure/providers/core_acquisition.py` 现对正式 Fuyao 结果再次验证规范身份、`direct-turnover` 与 exact `fuyao-market-v2`，并把 `canonicalIdentity`、`amountEvidence`、`sourceRevision` 保留到 payload、provenance、fingerprint 和 typed quality evidence。
- core 生产 composition 与五个逐指数计划已由测试固定为 `Fuyao -> mootdx -> 百度 -> 新浪 -> 腾讯 -> 东方财富`；正式启用与 shadow 同开直接拒绝，v1 revision 不可 cutover，Fuyao 单项失败不丢弃 sibling success。
- `domain/policies/capability.py` 已注册 `fuyao/core/fuyao-market-v2` 自包含 evidence policy；`cli.py` 的 core report 明示 endpoint、五个 identity、OHLC/直接成交额、逐指数 exact date/280 bars、权限和预算，禁止 shadow/comparison/tolerance/provider-values。
- 已新增 complete `deploy/truenas/values-fuyao-core-off.yaml` 与 `values-fuyao-core-enabled.yaml`。两份源文件除 `core.enabled` 外逐字节一致；render 均只有 Deployment、StatefulSet、两个 Service 和一个 PVC，不含 Secret、CronJob 或 Job。
- `scripts/validate-scheduling-packet.py` 已支持 `validate-core-packet`、`compare-core-config-only` 与 dataset-bound disabled Pod 选择；`scripts/deploy-truenas-k3s.sh` 已支持 `--stage-core-off`、`--promote-core-capability`、`--enable-core-config`、`--disable-core-config`，复用冻结 packet、clean worktree、exact Pod、masked database、hash binding、`--no-hooks --atomic --wait` 和 preserved identity 门禁。
- task 6.2 写前复核发现 staged off 曾复用普通发布的 migration component 契约；现已收窄为一次完整、显式 `--no-hooks` 的 Helm write，写前后均要求 active run/task/lease=`0/0/0`，并在写前后复核 exact image digest。相关部署/packet 回归测试为 `120 passed`；修复完成前未执行生产写入。
- focused syntax/compile/test（2026-10-19）：

  ```bash
  bash -n scripts/deploy-truenas-k3s.sh
  .venv/bin/python -m py_compile \
    scripts/validate-scheduling-packet.py \
    src/market_environment/cli.py \
    src/market_environment/domain/policies/capability.py \
    src/market_environment/infrastructure/providers/core_acquisition.py \
    src/market_environment/infrastructure/providers/fuyao/config.py
  .venv/bin/python -m pytest \
    tests/test_market_environment_core_acquisition.py \
    tests/test_market_environment_capability_promotion.py \
    tests/test_market_environment_fuyao_collection_integration.py \
    tests/test_market_environment_fuyao_market.py \
    tests/test_market_environment_bootstrap.py \
    tests/test_market_environment_capability.py \
    tests/test_fuyao_core_deployment_profile.py \
    tests/test_scheduling_packet_validator.py \
    tests/test_truenas_scheduling_guard.py -q
  ```

  结果：`270 passed, 1 warning`；warning 为 Starlette `BlockingPortal` 弃用提示，与本 change 无关。
- Helm 离线验证（Kubernetes `1.26.6`）已通过：两份 `helm lint --strict` 均为 `0 failed`；两份 `helm template` 分别通过 `validate-core-packet --require-enabled 0/1`；`compare-core-config-only --from-enabled 0 --to-enabled 1` 通过。
- reviewed packet SHA-256（task 6.1 后按 live image/manual 状态刷新；本地离线 render，release/namespace=`a-stock`、Kubernetes `1.26.6`）：
  - core-off values：`7539b0532eeac34dbdc997e68f40e90a6c3cb67b53a25f30b79642f6f60f8b6c`
  - core-enabled values：`3958a34e384bd154e5b05314e4a0cd0ff524f0f0e9c775f74390006a4dcd9d10`
  - core-off render：`8e73e37bcb85e3b88b597e0143aef379d908c25c45c0c6d5b5444ce93b9f84d7`
  - core-enabled render：`400d16ed5a82e284c352896c181bb8c06a893c829e160d56d72dccc59e9d8181`
- task 6.2 生产 core-off 收敛（2026-10-19 22:32–22:40 Asia/Shanghai，用户仅授权本步骤）：
  - clean reviewed source 为 commit `4427fe1e62f2468a256a045d2ce238fc290cb7eb`；新镜像 `localhost/a-stock-market-environment:20261019-223139-4427fe1`。chart SHA-256 为 `64b95ddee1497f8f23391a414ca3303564b1d66e84fd97cc573514b0dca326fe`；off/enabled values SHA-256 分别为 `7539b0532eeac34dbdc997e68f40e90a6c3cb67b53a25f30b79642f6f60f8b6c` / `3958a34e384bd154e5b05314e4a0cd0ff524f0f0e9c775f74390006a4dcd9d10`；以 exact k3s `1.26.6+k3s-6a894050-dirty` 和新镜像渲染的 off/enabled SHA-256 分别为 `3457e250618866b332b9a10cfbcec5c9c69d0073472d32c637d669c30faf1950` / `925e3a3c18ea139d95582b3e4b65124e305eb4242ac414c70df369737724f31c`，config-only comparison 通过。
  - 首次受控入口因传入简写 Kubernetes `1.26.6`、现场返回完整版本而在 SSH/Kubernetes 只读检查阶段 fail closed；该次未 build/import/Helm write。随后以完整版本重跑，同一 packet 通过。
  - 镜像本地 health smoke 通过；archive SHA-256 为 `4eb680ed992eee442720ab925c19540b72e1186b2e0f46a0d1b95a2e1bfacb57`，远端校验通过；containerd manifest digest 为 `sha256:0cfc94c5bb313d1091e7060811991100556713784a2885d626e20adaf4d5dce3`，运行 Pod imageID 为 `sha256:32c37893deae0682a924920757b92148d2f6052d8d5ca69ea0f7ee19e3e8807c`。
  - 唯一 Helm write 使用完整 release、`--no-hooks --atomic --wait`；未运行 database/service component migration，Helm revision `144 -> 145`、status `deployed`。新 owner chain 为 Deployment `a-stock` → ReplicaSet `a-stock-8456d79cc` → Pod `a-stock-8456d79cc-pcfw4`，`1/1 Ready`、restart `0`；PostgreSQL 仍 `1/1 Ready`、restart `0`。
  - runtime 为 formal core `0`、shadow `0`、approved revision `fuyao-market-v2`；sectors 仍 enabled v2/shadow 0，manual refresh `1`、automation refresh `1`。CronJob=`0`、Job=`0`；`/api/health` 与 provider-free `/api/market-environment/core` 均 HTTP 200。
  - metadata-only preserved identity 未变：provider Secret UID `81b9d039-7d77-44bc-9c4f-41b9ce2e19b2`、PostgreSQL Secret UID `653a79bf-a881-43de-8623-2d9f69e9aa0f`、`a-stock-data` PVC UID `c03bc7f8-2935-41d6-ba63-b1e9e26b8ffe`、PostgreSQL PVC UID `6c426fc5-10e2-4e88-b534-b258c70869c4`；Service 为既有 `a-stock` UID `0a6fcb84-c6f1-49be-a0c1-7765b24ba254` / NodePort `32001` 与 PostgreSQL UID `2d9438a7-540a-4b83-aa96-ef72a115fe56` / ClusterIP。各资源 creationTimestamp 均早于本 rollout，未重建。
  - capability rows 仍为 4，`fuyao/core/fuyao-market-v2` 仍为 0 行；既有 sectors checksum 仍为 `b763a32e56b111e449f078c5af203db25cd328c4e98a9f821edf040936240b2a`。写前后 active run/task/lease 均 `0/0/0`；`2026-10-19 22:30 +08:00` 起新增 collection run/task/snapshot/aggregate 为 `0/0/0/0`，证明本 rollout 未触发 provider、promotion 或 collection。
- task 6.3 fresh Fuyao core real probe（2026-10-19 22:53 Asia/Shanghai，用户仅授权本步骤）：
  - 从 clean detached commit `80948c96833bb5d4f6b4cadf200980d48b62ad27` 在上海当日结算后只执行一次 `fuyao real-probe --allow-real --as-of 2026-10-19`；API key 仅从既有 `a-stock-market-provider` Secret 注入该进程，未打印、未写入仓库或输出文件。
  - 隔离证据目录为 `/home/gyt/.local/share/a-stock/fuyao-core-probes/20261019-core.VnPXxY`（目录 mode `700`，三个文件 mode `600`）；受审 envelope 为 `fuyao-real-envelope.json`，SHA-256 `c9be20d9cedfd818709effbb3ce99213f8142c73baeb63f0681d99b439a05d09`；隔离 SQLite SHA-256 `7e9a244516f868e13256580f2c483246f83e463106eb9b4048c5f385784fcbb3`。
  - 精确选中 `fuyao/core/fuyao-market-v2`；report status=`eligible`、endpoint=`/api/a-share-index/prices/historical`、canonical checksum=`2f05d46e585a8ef703dd35270f68b2a7f0b6056765e41c4e172759fbe54045c5`，canonical redaction 与 envelope 完全一致，`missingEvidence=[]`、warnings 为空。
  - 五个 identity 均精确匹配：`sh000001 -> 000001.SH`、`sz399001 -> 399001.SZ`、`sz399006 -> 399006.SZ`、`sh000300 -> 000300.SH`、`sh000905 -> 000905.SH`；每项 `lastValid=2026-10-19`、`exact=true`、observations=`484`，OHLC/turnover 完整且 `directTurnover=true`，合计 sample count=`2420`。
  - 权限证据为 `configured=true / approved=true / mode=explicit-real-probe`；请求预算为 used/budget=`5/80`；当日腾讯独立报价仅执行当前价 sanity check，`checked=true / sampleCount=5`，没有保留其数值。policy 明确证明无 shadow、comparison、tolerance、provider-values 或多日对账字段。
  - `ProviderCapabilityReport.from_dict` checksum 验证和 `validate_fuyao_core_v2(..., 2026-10-19)` 均通过；stdout envelope 与文件一致，SQLite 中的 core row 与受审 report 字节语义一致，API key 对 JSON/stdout/SQLite 的字节扫描为 0 命中。
  - 生产只读后检仍为 Helm revision `145`、Pod `a-stock-8456d79cc-pcfw4` Ready、镜像 `localhost/a-stock-market-environment:20261019-223139-4427fe1`、formal core=`0`、shadow=`0`、approved revision=`fuyao-market-v2`；生产 core capability 仍为 0 行，probe 窗口新增 run/task/snapshot/aggregate=`0/0/0/0`，active run/task/lease=`0/0/0`。本步未写生产数据库，未修改 Helm/config/Secret/PVC/Service，未触发 promotion、core enable 或 collection。
  - task 6.3 证据更新后 `openspec validate activate-fuyao-core-provider --strict`、`python3 scripts/check-docs-contract.py --mode=full`（代码 0 / 文档 2 / plan 1）和 `git diff --check` 均通过。
- task 6.4 reviewed capability promotion（2026-10-19 23:00–23:01 Asia/Shanghai，用户仅授权本步骤）：
  - 受控入口从 clean detached commit `4427fe1e62f2468a256a045d2ce238fc290cb7eb` 执行，绑定 chart SHA-256 `64b95ddee1497f8f23391a414ca3303564b1d66e84fd97cc573514b0dca326fe`、off/enabled values SHA-256 `7539b0532eeac34dbdc997e68f40e90a6c3cb67b53a25f30b79642f6f60f8b6c` / `3958a34e384bd154e5b05314e4a0cd0ff524f0f0e9c775f74390006a4dcd9d10`、off/enabled render SHA-256 `3457e250618866b332b9a10cfbcec5c9c69d0073472d32c637d669c30faf1950` / `925e3a3c18ea139d95582b3e4b65124e305eb4242ac414c70df369737724f31c`。
  - 报告仍为 SHA-256 `c9be20d9cedfd818709effbb3ce99213f8142c73baeb63f0681d99b439a05d09`，canonical checksum `2f05d46e585a8ef703dd35270f68b2a7f0b6056765e41c4e172759fbe54045c5`；通过 stdin 直接流式传入 exact Ready Pod `a-stock-8456d79cc-pcfw4`，未使用 `kubectl cp`、TTY、Pod 临时文件，也未导出数据库 URL 或凭据。
  - dry-run 返回 `result=validated / mode=dry-run / conflictState=absent / status=eligible`，provider/dataset/revision 为 `fuyao/core/fuyao-market-v2`，target backend 只显示 `postgresql+psycopg://***@a-stock-postgresql:5432/a-stock`；同一文件 apply 返回 `result=applied / mode=apply / conflictState=absent`。
  - 生产 `provider_capability_reports` 总数 `4 -> 5`，新增目标恰好 1 行：`eligible`、endpoint `/api/a-share-index/prices/historical`、sample count `2420`、schema version `1`、checksum 与受审 report 一致；其他 capability 的全行指纹 `d6f20cdd165839d4042327c6b8d23431` 前后不变。
  - snapshot `134 / a5d01390afd3ca608c6bb64c2586aa7a`、collection run `112 / 90d952866a16fce6f1f3078c20e143f7`、task `273 / 673e65906f6d78d3a17b408be7e3ed0b`、aggregate `32 / 793a277e7b9ddc700a2fedbe9a4b0310` 的 count/全行指纹前后完全不变，active run/task/lease 仍为 `0/0/0`。
  - Helm 仍为 revision `145`，Pod UID `413e74b2-d255-4c0e-a6fa-101c4c1a18b0`、Ready、restart `0`、镜像和 imageID 前后不变；formal core=`0`、shadow=`0`、approved revision=`fuyao-market-v2`。Secret/PVC/Service UID 与 task 6.2 记录一致，CronJob/Job=`0/0`，未修改 configuration 或 deployment，未调用 provider、未启用 core、未触发 collection。
  - 隔离操作日志保存于 `/home/gyt/.local/share/a-stock/fuyao-core-promotions/20261019-core.uhHBAy`（目录 mode `700`、文件 mode `600`）；dry-run/apply log SHA-256 分别为 `3553da8069183e5ce072965ab382534610d8f56484d517f7bf6d27f85bb54bae` / `ffa9e094e349cf1887380503b654111319b5776fb6d17cbd3060aadbf8f74f86`。
  - task 6.4 证据更新后 `openspec validate activate-fuyao-core-provider --strict`、`python3 scripts/check-docs-contract.py --mode=full`（代码 0 / 文档 2 / plan 1）和 `git diff --check` 均通过。
- task 6.5 same-image formal core enable（2026-10-19 23:22–23:23 Asia/Shanghai，用户仅授权本步骤）：
  - 受控 `--enable-core-config` 入口从 clean detached commit `4427fe1e62f2468a256a045d2ce238fc290cb7eb` 执行，绑定 exact k3s `1.26.6+k3s-6a894050-dirty`、镜像 `localhost/a-stock-market-environment:20261019-223139-4427fe1`、manifest digest `sha256:0cfc94c5bb313d1091e7060811991100556713784a2885d626e20adaf4d5dce3` 以及 task 6.4 已记录的 chart/values/render SHA-256。
  - 写前再次读回唯一 `fuyao/core/fuyao-market-v2` eligible row：sample count `2420`、checksum `2f05d46e585a8ef703dd35270f68b2a7f0b6056765e41c4e172759fbe54045c5`；formal core/shadow=`0/0`，active run/task/lease=`0/0/0`，CronJob/Job=`0/0`。
  - 唯一 Helm write 使用完整 reviewed core-enabled profile 与 `--no-hooks --atomic --wait`，release revision `145 -> 146`；写前 validator、写后 exact release/live validator 及独立 `compare-core-config-only` 均通过。raw Helm manifest diff 只有 `MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED: "0" -> "1"`，diff SHA-256 `d36b28cfc6ae02f2efb9409ffae40417cf876a7fc65348f995e2bcc942a863cd`。
  - 新 Pod `a-stock-d5b456854-d7xmj` Ready、restart `0`，仍为同一 imageID `sha256:32c37893deae0682a924920757b92148d2f6052d8d5ca69ea0f7ee19e3e8807c`；formal core=`1`、approved revision=`fuyao-market-v2`、shadow=`0`。PostgreSQL StatefulSet 仍 `1/1 Ready`并保持同一 digest。
  - capability `5 / 894924f6027af4d0a542add6ac6c45f7`、snapshot `134 / a5d01390afd3ca608c6bb64c2586aa7a`、collection run `112 / 90d952866a16fce6f1f3078c20e143f7`、task `273 / 673e65906f6d78d3a17b408be7e3ed0b`、aggregate `32 / 793a277e7b9ddc700a2fedbe9a4b0310`、refresh run `0 / d41d8cd98f00b204e9800998ecf8427e` 的 count/全行指纹前后逐字一致；active run/task/lease 仍为 `0/0/0`。
  - provider Secret、PostgreSQL Secret、两个 PVC 和两个 Service 的 UID/resourceVersion/存储或网络 identity 文件前后完全一致，CronJob/Job 仍为 `0/0`。`/api/health` 与 provider-free `/api/market-environment/core` 均 HTTP 200，响应 SHA-256 前后分别稳定为 `a29ee2b15c494311c52521766e44af56a3ad2248e7a8ab465e5206463c13d288` / `55d55e008c54156143427a875ca53d9a3e20fb37c8ede284f000a3a04d58a21a`。
  - 隔离操作证据保存于 `/home/gyt/.local/share/a-stock/fuyao-core-enables/20261019-core.hGUb9q`（目录 mode `700`、文件 mode `600`）；enable log SHA-256 `8dbdfc766918cbeedcb0d13d9f3ad92f3557ad3b74de0e603da178afbe1d787b`。本步未调用 provider、未触发 collection、未修改 capability/snapshot/task/aggregate，也未执行 task 6.6。
  - task 6.5 证据更新后 `openspec validate activate-fuyao-core-provider --strict`、`python3 scripts/check-docs-contract.py --mode=full`（代码 0 / 文档 2 / plan 1）和 `git diff --check` 均通过。
- 仓库内实现与离线验证阶段未调用真实 Fuyao、未读取/修改 Secret、未连接生产数据库、未执行 SSH/kubectl/Helm 生产操作、未触发采集或回滚；随后 task 6.1 只进行了明确授权的只读 SSH/Kubernetes/Helm/PostgreSQL `SELECT` preflight。
- 最终离线门禁（2026-10-19）：
  - `.venv/bin/python scripts/check_market_environment_architecture.py`：`market-environment architecture: OK`。
  - `.venv/bin/python -m pytest tests -q`：`1559 passed, 6 skipped, 2 failed, 1 warning`。两处失败均为本工作树既有 `repair_integrity` 改动与旧 test double 签名不一致：`tests/test_market_environment_commands.py::test_collection_and_aggregate_command_use_cases_delegate_through_ports` 的 `FakeCollectionCommands.refresh()`、`tests/test_market_environment_refresh.py::test_cli_outputs_structured_refresh_result` 的 `FakeCoordinator.collect()` 不接受 `repair_integrity`；它们不涉及 Fuyao core，本 change 未越界修改该用户工作。
  - `openspec validate activate-fuyao-core-provider --strict`：通过。
  - `python3 scripts/check-docs-contract.py --mode=full`：通过（代码 13 / 文档 7 / plan 2）。
  - `git diff --check`：通过。
- task 6.1 生产只读 preflight（2026-10-19 22:07–22:12 Asia/Shanghai，用户仅授权该只读步骤）：
  - k3s client/server 均为 `v1.26.6+k3s-6a894050-dirty`；Helm release `a-stock/a-stock` revision `144`、status `deployed`、chart `a-stock-0.1.1`，最后部署时间 `2026-10-17 01:16:52 +08:00`。
  - Dashboard Deployment/ReplicaSet/Pod 为 `a-stock` → `a-stock-54b994d888` → `a-stock-54b994d888-knzb5`，`1/1 Ready`、restart `0`。现场镜像为 `localhost/a-stock-market-environment:20261017-005702-d12dae3`，Pod imageID 为 `sha256:490521ec7a1ad044585777151658947433c7e01c6a27def202197c6e8647ed8b`；PostgreSQL StatefulSet/Pod `1/1 Ready`、restart `0`，镜像 digest 仍为受审 `postgres:16.4` digest。
  - 两个历史 CronJob identity 与全部 namespace Job 均 absent。应用 Service 为 NodePort `32001`，PostgreSQL Service 为 ClusterIP；健康检查 `/api/health` 返回 `{"status":"ok"}`。
  - metadata-only identity：provider Secret UID `81b9d039-7d77-44bc-9c4f-41b9ce2e19b2`，PostgreSQL Secret UID `653a79bf-a881-43de-8623-2d9f69e9aa0f`；PVC `a-stock-data` UID `c03bc7f8-2935-41d6-ba63-b1e9e26b8ffe` / 2Gi / Bound，PostgreSQL PVC UID `6c426fc5-10e2-4e88-b534-b258c70869c4` / 5Gi / Bound。未读取任何 Secret 值。
  - runtime core flags：formal `MARKET_ENVIRONMENT_FUYAO_CORE_ENABLED=0`、shadow `=0`，但没有 `MARKET_ENVIRONMENT_FUYAO_CORE_APPROVED_REVISION`；sectors 保持 enabled v2。manual refresh 当前为 `1`、automation 为 `1`。
  - masked PostgreSQL target 为 database/user `a-stock|a-stock`。`provider_capability_reports` 共 4 行；`fuyao/core/fuyao-market-v2` 不存在，现有 `fuyao/sectors/fuyao-market-v2` 为 eligible，checksum `b763a32e56b111e449f078c5af203db25cd328c4e98a9f821edf040936240b2a`。active collection run/task/lease 均为 `0/0/0`。
  - 最近 core task（as-of `2026-10-19`）为 success、source `tencent-kline`、5 indices，warning 明确五个指数均因通达信/百度/新浪不可用降级到腾讯且历史成交额可能不可用；与本 change 动机一致。更早记录包含百度/腾讯混合成功、腾讯成功、worker-interrupted retained failure 和新浪成功，不存在 Fuyao core 正式证据。
  - preflight 只执行 SSH、Helm/Kubernetes metadata GET、Pod 内本地 health GET 与 PostgreSQL `SELECT`；未调用 Fuyao/其他 provider、未执行 collection、未读取 Secret 值、未写数据库、未执行 kubectl/Helm mutation。
  - 结论：生产不是 reviewed core-off 的精确状态；至少缺少 core approved revision，且当前运行镜像不包含本 change 的新 policy/CLI/deployment guard，因此不得直接执行 capability promotion、core enable 或采集。若继续，下一步必须是 task 6.2 的完整 reviewed core-off 收敛，并另行授权。
  - preflight 后仅在仓库内刷新 paired profiles：基线 image tag 改为现场 `20261017-005702-d12dae3`，manual refresh 保持现场 `1`；两份 profile 仍只差 core enabled flag，shadow 均关闭。部署/packet focused tests 重跑为 `118 passed`，双 strict lint 与 core config-only comparison 通过；上述四个 SHA-256 已替换旧值。该本地更新未访问或修改生产。

## Remaining Gaps（剩余缺口）

- OpenSpec 生产任务 6.6–6.7 和最终生产 handoff 7.1–7.2 尚未完成；不得 archive。
- 全量 backend suite 仍有上述 2 个与本 change 无关的既有 `repair_integrity` test-double 失败；本 change 的 270 项 focused suite 全部通过。若要求全仓零失败，需由对应 repair plan 同步它的测试替身签名后重跑。
- task 6.1–6.5 已完成；formal core 已为 `1`且 shadow 仍为 `0`。单次 core-only 采集和条件回滚仍未授权。
- fresh core capability report 已精确写入生产 `provider_capability_reports`并通过启用前门禁，但尚未进行单次 core-only 生产验收，因此尚不能声明五指数 full all-Fuyao 成功。
- 用户已明确接受不做跨 provider 对账可能无法发现“字段完整但成交额语义不同”的风险；不得在本 change 中擅自恢复 shadow 或对账。

## Next Step（下一步）

暂停并等待 task 6.6 的独立授权：仅在上海当日结算后运行恰好一次 core-only 采集，核对五个指数的 exact date、source、revision、observations、`direct-turnover` 和 warning。五项全来自 Fuyao 才标记 full；任一 fallback 则标记 partial 并保留真实来源/Fuyao failure，不自动重试、不对账。

# 测试棘轮与提交门禁

## Stage
实施 OpenSpec `add-test-ratchet-and-commit-gate`：HTTP 验证、三事实测量、本地分层 hooks、现有 CI 整合与最终验收。

## Status
completed（31/31）。三轮全量均 1803 passed / 0 skipped，最终 CI 与上一轮的三事实精确一致，正式基线未被普通 CI 改写。用户明确确认后当前仓库三个 hooks 已安装且 --check 为 active。规格/文档/差异验收通过；实施与归档阶段未提交或推送，未改变生产环境。随后用户单独授权提交本次变更，仍不推送。

## Acceptance
- 全部声明的 API/discovery method/path 由通过测试成功调用，排除前端 catch-all/static/framework docs。
- 三事实：sorted pytest node inventory、passing-test HTTP operation set、src/ 逐文件未覆盖语句上限；普通验证不写基线。
- 暂存树必须与非 ignored 工作树相符（包括文档/fixture），不 stash、不改 index；refs 精确传给 docs full。
- commit/push 为范围测试，建议 30s/180s；CI 为一次 coverage 全量后端加 Vitest/build。超时只能告警，失败不能伪装通过。
- PostgreSQL 同 CI digest、隔离数据库，数据库缺失/skip、profile 不匹配、旧报告、空 coverage 必须 fail closed。
- 应急理由由 commit-msg 审核，CI 丢弃本地 bypass；保留现有 workflow 名称/job identity 与数据库配置。

## Completion Evidence
### 测量与基线
- 首次启用 PostgreSQL 的全量：1802 passed / 1 failed / 0 skipped，665.03s（dispatcher 683.92s）。现有事务测试 core fixture 缺日期证据，用户明确授权仅补 fixture；没有改应用/dataset/skip 或放宽提交/回滚断言。
- 授权修复的相邻 PostgreSQL/integrity/core-date 回归：16 passed，0.53s。
- 首轮绿色全量：1803 passed / 0 skipped，437.88s（dispatcher 444.54s）；101 个 DB 集成节点全部运行。
- 真实 passing-test operation set 与 OpenAPI 精确相同：39/39。新增 health、v2 breadth、workbench 共 6 个用例；相邻 HTTP 组 24 passed，4.06s。
- coverage 7.17.0 原始报告：236 个 src 文件；27304 statements、22855 covered、4449 missing；83.705684% 仅为信息，不设百分比阈值。
- 初始 converter 曾误用 num_missing，实际 coverage 7 summary 字段是 missing_lines，导致空集合。已修正并增加真实格式/空数据拒绝回归；不接受该空基线。从同一全绿原始报告显式重建初始基线，逐项核对 236 文件/4449 missing 与 totals，并存报告 SHA-256 和版本/digest metadata。没有用失败报告或探索性 83% 生成事实，也没有伪造第二次测量。
- 基线：`tests/baselines/test-ratchet.json`；首轮原始报告：`/tmp/a-stock-ratchet-green-1/pytest.json` 与 `coverage.json`；第二轮输出 `/tmp/a-stock-ratchet-green-2/`。原始报告不入库。
- 测量/门禁最终 focused：58 passed，4.43s；节点数量不变。覆盖真实 ASGI method/template/status、error-only、patch 恢复、PID/run token、旧报告拒绝、空/非法 coverage、trusted parent、防伪 rename、candidate admission、普通 CI baseline 只读、docs 精确范围、跨平台 shell 模拟。
- 对真实基线的内存退化注入：删 test inventory、删 operation、增 uncovered、提高 proposed baseline 上限均被拒绝；实际缺 DB 的 `--mode=ci` 非零退出（0.18s）且 baseline SHA 不变。

### 分层与 Hooks
- 临时真实 Git 仓库：`/tmp/a-stock-hook-acceptance-lzpzjo1g`，仅在此创建 fixture commits。安装器和 --check 均 active；没有在用户仓库提交/创建分支/发布。
- docs-only commit：墙钟 0.23s，gate 0.09s；选中单个 fixture test 的 commit：墙钟 0.54s，gate 0.37s。
- 真实 selected test 失败会阻断且 HEAD 不变；应急缺 marker 会阻断；完整相同理由 marker 才允许 unverified recovery（pre-commit 0.04s、message 0.00s）。
- 最终 refs 精确范围 push dispatcher：墙钟 3.52s（gate 3.47s），docs full 实际看到代码 1 / 文档 2 / plan 1，随后 architecture/rules validate/coverage/selected pytest 通过；无 remote write。
- 这些是小型范围案例，不能外推任意源模块/广泛提交的耗时。30s/180s 为建议预算，范围回退预先选择，超限告警绝不覆盖失败或把未完成测试当通过。
- 曾发现无 upstream 的旧 docs full 空检；已用严格 DOCS_CONTRACT_DIFFS 协议修正，多 refs/new branch/deletion/invalid ref/CI target 均有回归。

### CI、前端、依赖
- workflow 文件/name `Trading Rules PR Gate`/job `offline-rule-gate` 保持；PostgreSQL digest 与 test URL 保持。checkout full history；Node 22 + lockfile npm ci；Vitest 与 build 在 backend 前完成；仅一次 coverage pytest，报告供棘轮复用。
- 本地独立 PostgreSQL 16.4 image RepoDigest 与 CI 完全相同：sha256:9a70e4d1c03a5066080292db2dd95ee3965d3651316e21989fa0935afb8ce8ca。
- rootless 既有 `/run/user/1000` tmpfs 已满；用户明确授权新的 `/tmp/a-stock-ratchet-isolated-20261027` root/runroot/runtime。custom runtime 无 session bus，第二容器使用 cgroupfs/cgroups disabled，未改原有容器存储或生产服务。
- dashboard：24 files / 172 tests passed；build 2193 modules 成功；墙钟 128s/74s 含并发 setup 竞争，不能当正常预算。仅既有 Vue Router/large chunk warnings。
- architecture、rules validate（49）、rules coverage/docs sync-check（330 documented/49 executable）通过。
- coverage>=7,<8 已安装，pip check 无冲突；clean dependency solve `--dry-run --ignore-installed -r requirements.txt` exit 0（663s，setup 下载不算测试预算）。
- 一轮旧并发 smoke 2 failed/87 passed：Vite build 清空 dist/assets 与 app factory 竞态、测试变量清理时读旧代码。未改应用或削弱测试；后续冻结代码、不并行构建，首轮绿色全量已覆盖同节点。正式 profile 现在明确要求已构建 dashboard。

### 最终验收
- 第二轮 CI：1803 passed / 0 skipped，413.96s（dispatcher 419.74s）。CI gate 成功且基线只读；额外严格相等检查发现唯一 refresh 缓存复用3行的调度差异（missing30→27），因此没有直接宣称确定性完成。随后以既有测试节点确定性补齐并显式收紧，第三轮证明计数稳定。
- 第三轮 CI：1803 passed / 0 skipped，398.96s（dispatcher 404.75s），101 个 DB 节点全部通过。inventory/39 operations/236 个逐文件 ceilings/profile 与第二轮测量完全一致。
- 最终 missing4446 / 27304 statements（22858 covered，83.716672%）；refresh.py 仅从30收紧为27，没有提高任何上限。既有 refresh 节点扩展后 focused 7 passed，两份独立 coverage 的141条 executed_lines 完全一致，201/202/214均必定执行。
- 普通 CI 未改写基线，SHA-256：8c970a74857e3fc00f7712b3f826e4a09be6257d3c4a597880a15a16c716617f。实际注入本地 test/docs/plan bypass 和空 diff override，均被 CI 清除后完成全部测试与 docs full。
- 用户明确确认后当前仓库 install / --check 均 active（pre-commit/pre-push/commit-msg）；仅 local config/权限，无 index/stash/commit 变化。
- OpenSpec strict、docs full、tracked git diff --check 均通过；15 个 untracked deliverables 也以 no-index --check 验证干净，没有暂存。
- 已核实并停止本次独立 PostgreSQL 容器 3c0c8a3aba3da0c680dd33ec2ac6ba4130688d96eff1b4bb6c8e616eefccf90e；独立临时存储和原始报告保留供复查，不删除任何原有资源。

### OpenSpec 归档
- 用户请求归档，并明确选择先同步主规格。`repository-test-gate` 新增10项要求；`trading-rule-ci` 更新离线 PR 要求并新增1个场景，保留其余要求/场景。
- 逐项复核两份增量均无剩余待应用内容；全部17份主规格常规验证通过，选定变更 strict 验证通过。
- 全仓额外 strict 检查因7份既有 Purpose 占位警告未通过（包含 trading-rule-ci 的原有 TBD）；遵循本次范围保留既有 Purpose，未顺带修改其他能力。
- 已归档至 `openspec/changes/archive/2026-10-27-add-test-ratchet-and-commit-gate/`，目标原不存在，`.openspec.yaml` 原样保留，31/31任务完成；未提交或推送。

## Remaining Gaps
- 本次31项实现/本机验收无剩余阻塞。
- Windows/macOS 真机及远端 GitHub Actions/branch protection 本会话未执行；已做可用 shell/解释器模拟，保留 workflow identity，不修改 required checks。

## Next Step
OpenSpec 已同步并归档；用户已授权本次实现、主规格、基线及归档进入 Git 提交，不执行推送，不使用门禁 bypass。当前 hooks 已启用，提交前应整理暂存区及非 ignored 工作树；未来基线更新须显式理由且不能放宽既有保护。Windows/macOS 真机、远端 Actions 及既有 Purpose 占位告警可另行跟进，不以本会话模拟或常规验证替代。

## Safety
仅使用 synthetic fixtures 和新建 loopback PostgreSQL。无真实 provider、生产 DB、部署、Kubernetes/Helm 或调度写入；未清理任何原有容器/镜像/文件。实施与归档阶段未在用户仓库提交；现仅按用户新授权提交本次变更，不创建分支、不 push；临时 Git fixture 不发布。未修改应用源代码。

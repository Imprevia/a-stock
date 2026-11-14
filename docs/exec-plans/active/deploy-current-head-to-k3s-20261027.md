# 部署当前版本到 TrueNAS k3s（2026-10-27）

## Stage（阶段）

生产发布与发布后只读验收完成。

## Status（状态）

completed-with-production-write

## Scope（范围）

- 用户要求“部署到 k3s”，将当前已提交 HEAD `1bfe367051049197573a99883fb0b2e086f91cf7` 发布到既有 `192.168.1.20` TrueNAS k3s，namespace/release 均为 `a-stock`。
- 使用独立 clean detached worktree、精确 `REVIEWED_GIT_HEAD` 与受支持入口 `scripts/deploy-truenas-k3s.sh --component all`；不创建分支或提交。
- 从现场 revision 149 完整 values 冻结 baseline，保持单副本、NodePort 32001、Secret/PVC identity、manual/automation 和 Fuyao/THS 开关不变；现场 `database.migration.schemaEnabled=true`，无需改变 baseline，受控入口完成一次幂等 schema head 校验。
- 不触发 provider/collection、不修改外部调度器、不启停 gate、不创建 CronJob、不删除或替换 Secret/PVC，不直接修复业务数据。

## Acceptance（验收）

- 发布源 clean 且绑定完整 HEAD；明确候选有无新增 Alembic revision。
- 离线脚本语法、Helm strict lint、1.26.6 三组件 render、部署安全与业务回归通过；隔离 PostgreSQL 缺失导致 skip 时明确记录，不当作 SQL 验证通过。
- build/write 前 stored manifest 无 CronJob，两个 exact former CronJob 与 namespace Job absent，节点及 PostgreSQL Ready。
- 受控入口完成镜像本地 smoke、导入与 database → service → full release 收敛，Ready Pod tag/digest 与冻结镜像一致。
- 发布后只读健康、首页、同一历史日 v2 overview/池分页/晋级及主要 legacy GET 正常，不调用 provider。
- Secret/PVC identity、NodePort、安全上下文、单副本及业务开关不漂移；本地 docs-contract full 通过。

## Completion Evidence（完成证据）

- 初始工作树 clean，HEAD `1bfe367051049197573a99883fb0b2e086f91cf7`；前次发布 commit `16d9b3ecf81a01f66f7bd26abd4336dc56a2002e`。
- 只读预检：Helm revision 149 deployed，chart `a-stock-0.1.1`；`ix-truenas` Ready，k3s `v1.26.6+k3s-6a894050-dirty`；Dashboard/PostgreSQL 均 1/1、0 重启；两个 PVC Bound，NodePort 32001；两个 former CronJob 与 namespace Job absent。
- 私有发布包位于 `~/.local/share/a-stock/deploy-packets/20261027/`，凭据与运行时产物不进入仓库。
- 脚本语法、Helm strict lint、k3s 1.26.6 的 database/service/all 三包离线 render 与 docs-contract full 均通过；render 无 CronJob，仅 database/all 含精确 schema hook。
- 四组定向测试分两次成功执行，共 309 passed、0 skipped、0 failed：部署/调度 guard 200 条；PostgreSQL pools 与每日分层消费者 109 条。首次无测试库时 81 skip 不作为通过证据；补测使用专属 PostgreSQL 16.4 空库 `127.0.0.1:55439/release_contract_tests`，临时表/事务回滚，GET provider/DML guard 通过，前后 public 表数均 0。专属容器正常停止，保留卷、不影响其他容器。
- 现场 baseline SHA-256 `ceafbfca6b50f9fa098021bc697d01a83bc726a27ccf6040e436319ae1c0217c`，无需 values 差异；只读事务确认 schema=`0008_collection_idempotency`，active run/task/lease=`0|0|0`。候选无新增 migration/部署合同变更。
- 发布前只读审计计数：collection_runs=129、collection_tasks=320、refresh_leases=0、snapshot_entries=169、materialized_market_environment=37。
- 发布前精确日期 2026-10-26 三池（limit_up/limit_down/failed_limit_up）HTTP 200 但明细均 0，quality=degraded；promoted HTTP 500。本次部署包含已通过隔离 PostgreSQL 验收的读取修复，不重采或修复存量数据。
- 前端 Vite 生产构建通过；npm ci 报告 10 个依赖漏洞（4 moderate、3 high、3 critical），以及既有大 chunk 提示。本次仅发布已提交代码，不执行 `npm audit fix` 或扩大依赖升级范围；依赖安全处置另行评估。
- 已启动受控 `--component all` 发布，使用独立 clean worktree 与私有无凭据 env，镜像 tag `20261027-143500-1bfe367`。
- 最终受控发布 exit 0：2026-10-27 15:41–15:42 Asia/Shanghai 完成 revisions 150（database，唯一 schema hook）/151（service，no-hooks）/152（完整 release，no-hooks）；最终 revision 152 deployed，两个 former CronJob 与 namespace Job absent。
- 镜像 `localhost/a-stock-market-environment:20261027-143500-1bfe367`，archive SHA-256 `152d0e4ae18a42add70811bbeb7b1eeef0e28cd7ec55e1b05fbdf821f46ecaf3`，containerd manifest digest `sha256:83c553f9f10484155bf0e8c1f4dfae6654ded2723eb7b57bd629eae06246afad`；Pod `a-stock-7485d86c87-vxbjw` Ready、0 重启，runtime imageID `sha256:00fab3f918314193b85e4d9228c3aa564b4e2494a2386dfda0026c64e9db3301` 与本地构建 config 一致，受控入口 owner-chain/digest 验证通过。
- 完整 values 与 Deployment spec 分别比较均仅 image tag/image 差异；单副本、安全上下文、NodePort 32001、manual/automation 与 Fuyao/THS 开关不变。两个 PVC 仍 Bound，UID 分别为 `c03bc7f8-2935-41d6-ba63-b1e9e26b8ffe`、`6c426fc5-10e2-4e88-b534-b258c70869c4`；两个 Secret UID 与发布前一致。PostgreSQL Ready、0 重启。
- 发布后只读 smoke exit 0，保存 84 条脱敏检查记录：健康、首页、discovery/OpenAPI、2026-10-21/26 overview、indices、breadth、limits、三类 history 无/单边/双边日期与 limit=2 续页、legacy aggregate/core、三池及晋级全页。精确日期、revision、分页、身份、legacy 集合及晋级分子守恒均通过。
- 2026-10-21 三池全页为 50/5/19，晋级 16；2026-10-26 三池由空恢复为 55/26/23，晋级由 HTTP 500 恢复为 HTTP 200、15 条；保留来源、row warning、nullable 高级属性及原 degraded 质量，不宣称新采集成功。
- 当日 2026-10-27 未有证据：v2 overview、index/breadth/limits histories 与 breadth 均 404；legacy core 为既有 HTTP 503、detail“所选日期没有已采集的核心指数快照”。这是显式缺失，不是完整性损坏，不补采、不回退其他日期。补充检查的首轮严格只接受 integrity 503 因该 legacy missing 契约而停止，核对响应后按真实缺失记录，未修改应用。
- 发布前后 collection_runs=129、collection_tasks=320、refresh_leases=0、snapshot_entries=169、materialized_market_environment=37 完全一致；未触发 provider 或 collection。最终 `.venv/bin/python scripts/check-docs-contract.py --mode=full`（代码 23 / 文档 24 / plan 12）与 `git diff --check` 均通过，无豁免。

## Remaining Gaps（剩余缺口）

- 本次发布与只读验收无剩余执行缺口；当日无快照、历史 degraded/字段 warning 属于现有业务证据边界，不在部署中补采或伪造。
- npm 报告的既有依赖漏洞尚未处置，需另行评估；本次未运行全仓库 pytest 或真实 provider smoke，已运行部署与变更范围的充分定向测试和实际只读 smoke。
- 以下保留本次本机构建环境的恢复审计，不代表线上部署仍待完成。
- 依赖下载阶段默认 PyPI 大文件传输停滞约九分钟，受控任务在任何 Helm write 前取消；私有 Podman wrapper 仅对 build 临时只读挂载 `/etc/pip.conf`，指定 `https://mirrors.aliyun.com/pypi/simple/`（先验证 HTTP 200/0.35s），并以 `--pull-never` 复用已下载基础镜像后重试；不将镜像源配置写入最终镜像，保留源码与业务配置不变。
- 仅设置磁盘 `XDG_RUNTIME_DIR` 不足以覆盖现有 Podman 数据库绑定的 runroot；本次改用私有 wrapper 指定全新 graphroot/runroot（均在磁盘），复制已有基础镜像、不改变 Dockerfile 或受控发布脚本、不操作已有无关容器。隔离存储首次执行因用户 systemd 总线不可用在 npm 构建前停止，进一步显式选择 `--cgroup-manager=cgroupfs`；两次失败均发生在 Helm write 前。

## Next Step（下一步）

维持常规只读健康观察；业务采集仍由既有外部流程持有。如需回退，检出受审 rollback commit，使用新不可变 tag 重跑普通受控入口；不得恢复历史含 CronJob 的 release、删除 PVC 或自行修复业务数据。

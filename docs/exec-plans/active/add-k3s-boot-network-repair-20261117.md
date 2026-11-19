# 新增 TrueNAS k3s 开机网络修复受管单元（2026-11-17）

## Stage（阶段）

阶段 3：仓库资产、离线验证与节点安装完成；开机重启回归待维护窗口执行。

## Status（状态）

`installed-and-self-heal-verified / pending-reboot-regression`

## Scope（范围）

- 用户要求为已诊断的 TrueNAS `192.168.1.20` k3s 开机故障新增一个受管 systemd 单元，在开机后补齐 Pod 网段路由，并在 CNI 竞态时重启 k3s。
- 新增 `deploy/truenas/systemd/k3s-network-repair.sh`（执行体）、`a-stock-k3s-network-repair.service`（单元）与 `deploy/truenas/install-k3s-network-repair.sh`（安装/只读核查入口）。
- 单元只允许两类写入：节点因 CNI 未初始化而 NotReady 时重启 `k3s`（每次运行最多一次）；在 `kube-router` 路由表补齐 `cluster-cidr` 到 `kube-bridge` 的直连路由，以及缺失时的 `from <cidr> lookup kube-router` 规则。
- 不接管 TrueNAS 的 CNI/Multius 所有权，不修改 Helm release、values、PVC、Secret、NodePort、采集任务或业务数据，不创建任何 CronJob，不调用 provider。
- 文档同步 `docs/architecture.md`、`docs/runbooks.md`、`docs/repository-guide.md`、`docs/status.md` 与 `docs/lessons-learned.md`。

## Acceptance（验收）

- 单元文件可被 `systemd-analyze` 语义接受的指令集：`Type=oneshot`、`After` 覆盖 `network-online.target`/`k3s.service`/`kube-router.service`、`WantedBy=multi-user.target`，`ExecStart` 指向安装路径。
- 执行体幂等：健康时不产生任何写入；重复执行不重复添加路由；`--check` 只读并区分 healthy / repair-required。
- 离线测试覆盖：语法检查、无破坏性命令、healthy 直通、缺路由补齐、缺规则补齐、NotReady 时重启一次且不重启健康节点、无效 CIDR 拒绝、非 root 拒绝写操作。
- 安装入口支持 `--check` 只读漂移核查，且安装写操作在非 root 时 fail closed。
- `python scripts/check-docs-contract.py --mode=full` 与新增测试通过。

## Completion Evidence（完成证据）

- 现场诊断（2026-11-16 23:26 重启后）：`ix-truenas` 为 `NotReady`，kubelet 报 `NetworkPluginNotReady ... cni plugin not initialized`；`/etc/cni/net.d/10-kuberouter.conflist` 在 k3s 启动约 50 秒后才出现；`ip route show table kube-router` 仅有 `default via 192.168.1.1 dev br0`；`ip rule` 中 `32764: from 172.16.0.0/16 lookup kube-router` 已存在；`tcpdump -ni kube-bridge` 对 `host 172.16.92.47 and tcp port 8000` 抓到 0 包，证明流量被送到 br0。
- 按该诊断手工执行 `systemctl restart k3s` 与 `ip route add 172.16.0.0/16 dev kube-bridge table kube-router` 后，节点 5 秒内 Ready，Pod 探针通过，`/api/health` 与 v2 `overview` 恢复 200。
- TrueNAS `middlewared` 侧证据：`kubernetes_linux/cni.py` 的 `add_routes_to_kube_router_table()` 仅在 `lifecycle.py` 的 `post_start_internal()` 内执行一次，表同步失败后不会重试。
- 新增离线测试 `tests/test_k3s_network_repair_unit.py` 27 项，覆盖上述 Acceptance 项，全部通过；
  `tests/test_deployment_manifests.py` 151 passed；`python scripts/check-docs-contract.py --mode=full` 通过
  （代码 29 / 文档 14 / plan 5）；`git diff --check` 无告警。
- 节点安装已完成（2026-11-17 23:23 CST）：`enable` 后单元为 `enabled` + `active (exited)`，
  `ExecStart` 退出码 0、CPU 292ms。仓库与主机校验和逐字节一致：
  执行体 `12a7b4864db5526e7642ad2cbf93ab037befc7375e29a4c665fe84cbd472cf0b`，
  单元 `c30207069b14d8c39cee94a87383a02aeaf19901922c6485dedff8c1c644683b`。
- 自愈验证：先 `ip route del 172.16.0.0/16 dev kube-bridge table 77` 把路由表打回只剩默认路由的故障态，
  再执行安装入口；单元日志显示重新写入 `172.16.0.0/16 dev kube-bridge table kube-router`，
  随后 `check` 全部通过（节点 `ix-truenas` Ready）。生产链路同时复核：
  `a-stock` 与 `a-stock-postgresql-0` 均 1/1 Running，`/api/health` 返回 200。
- 安装过程中发现并修复两个真实缺陷：其一，`hostname` 返回 `truenas` 而 k3s 节点名是 `ix-truenas`，
  用主机名查询永远 NotReady，已改为按显式覆盖 → k3s 配置 → 集群唯一节点 → hostname 解析；
  其二，`RemainAfterExit=yes` 下对已 active 的单元执行 `systemctl start` 不会重跑修复，安装入口已改用
  `restart`。两者都有对应离线测试。

## Remaining Gaps（剩余缺口）

- 开机重启回归未执行：需要在维护窗口重启节点，确认开机后无需人工介入即 Ready，并回填首次开机的单元日志与路由状态。这是本计划唯一未闭合的验收项。
- 执行体只覆盖开机竞态导致的 CNI 未初始化与 kube-router 表缺路由两类故障；TrueNAS 升级若改变 CNI 文件路径或路由表名，需要同步调整默认值。
- 运行中 `k3s` 非开机原因重启导致表被清空时，本单元不会自动再次触发，需要手工 `systemctl restart a-stock-k3s-network-repair` 或重启节点。

## Next Step（下一步）

安排一次维护窗口重启 TrueNAS 节点，开机后执行 `sudo bash deploy/truenas/install-k3s-network-repair.sh --check` 与 `journalctl -u a-stock-k3s-network-repair.service -b`，确认节点无需人工介入即 Ready、路由表同时含默认路由与 `<cluster-cidr> dev kube-bridge`，回填首次开机证据后归档本计划。
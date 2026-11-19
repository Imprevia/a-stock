# 经验教训（lessons learned）

每条教训三段式：发生了什么 → 为什么重要 → 仓库因此改了什么。保持仓库相关，不写泛泛感言。

---

## 2026-08-29 · bootstrap 时选择 Python 作为 gate 运行时

- **发生了什么**：空仓库无既有运行时；基于 a-stock 数据分析定位与既有技能栈选择 Python。
- **为什么重要**：gate 运行时决定 hook 的可执行性；Windows 无 Python 时 hook 警告放行而非硬失败。
- **仓库因此改了什么**：`.githooks/*` 薄入口含 `python` → `py` 回退链；限制记录在 `docs/runbooks.md`。

## 2026-10-15 · 删除 CronJob 时默认级联回收了终态审计 Job

- **发生了什么**：生产 `--disable-schedule` 在 Helm keep 留下 suspended CronJob 后使用 Kubernetes 默认删除语义，owner-reference 垃圾回收随之删除原 `Failed=True` Job 与 Pod；PostgreSQL run/task 和删除前状态仍在，但原 Kubernetes 对象与日志不可恢复。
- **为什么重要**：终态 Job 是独立审计证据；“没有活动 writer”不等于可以删除失败/完成对象，数据库审计也不能冒充同一个 Kubernetes 对象。默认级联语义会让一次调度关闭产生不可逆证据缺口。
- **仓库因此改了什么**：`--disable-schedule` 在 Helm 写入前冻结完整 namespace terminal Job 集合，只允许显式 orphan propagation 删除 exact retained CronJob，并在删除前后比对 Job 集合、name、UID、计数与终态 condition；非终态、删除失败、Job 新增/丢失或漂移全部 fail closed。已丢失 Job 只登记缺口，禁止重建。

## 2026-11-17 · TrueNAS 重启后 k3s 的 CNI 与策略路由不会自愈

- **发生了什么**：2026-11-16 23:26 节点重启后 `ix-truenas` 一直 `NotReady`，kubelet 报 `NetworkPluginNotReady ... cni plugin not initialized`，旧 Pod 卡在 Terminating 九天、新 Pod Pending。根因是 TrueNAS 由 `middlewared` 在 `post_start` 阶段才写 `/etc/cni/net.d`，而 `k3s.service` 与 middleware 同属 `multi-user.target` 并行启动，k3s 在约 15 秒的检测窗口内看不到清单就永久停在 NotReady。重启 k3s 使节点在 5 秒内 Ready 后，又暴露出第二个故障：`ip route show table kube-router` 只剩 `default via 192.168.1.1 dev br0`，宿主机到 Pod 的流量被送去管理网桥，Pod 探针与 NodePort 全部超时；而 Pod 内访问自身 IP 返回 200，`tcpdump -ni kube-bridge` 抓到 0 个 SYN，证明丢包发生在宿主侧路由选择。`middlewared` 的 `add_routes_to_kube_router_table()` 只在 `post_start` 执行一次且不重试，`kube-router.service` 本身是 `disabled`。
- **为什么重要**：两个故障都是开机竞态，手工 `systemctl restart k3s` 加 `ip route add` 只能救活当次；`ip route add` 不持久化，下次重启必然复发，而且重启 k3s 会掩盖真正缺的是路由。只按 `NetworkPluginNotReady` 去“恢复 CNI/Multus 清单”会一直对着已存在的清单排查，`kubectl` 层的 Ready 状态也不会告诉你有多少流量被错误网桥吸走。
- **仓库因此改了什么**：新增受版本控制的主机级受管单元 `deploy/truenas/systemd/a-stock-k3s-network-repair.service` 与执行体，开机后补齐 `cluster-cidr dev kube-bridge table kube-router` 路由与 `32764` 策略规则，并只在 kubelet 明确报 CNI 未初始化时重启一次 k3s（每次开机至多一次）；管理网段重叠与非法 CIDR 一律 fail closed；安装入口提供 `--check` 只读漂移核查。`docs/runbooks.md` 的 TrueNAS 段由“先恢复 CNI/Multus 清单”改为按开机竞态处理并给出路由核查命令，`docs/architecture.md` 明确该单元只补位、不接管 middleware 的 CNI 所有权。新增 `tests/test_k3s_network_repair_unit.py`，用 stub 化的 `ip`/`systemctl`/`k3s` 离线覆盖幂等、重启预算、重叠拒绝与只读核查。

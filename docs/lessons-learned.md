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

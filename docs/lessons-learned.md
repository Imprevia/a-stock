# 经验教训（lessons learned）

每条教训三段式：发生了什么 → 为什么重要 → 仓库因此改了什么。保持仓库相关，不写泛泛感言。

---

## 2026-08-29 · bootstrap 时选择 Python 作为 gate 运行时

- **发生了什么**：空仓库无既有运行时；基于 a-stock 数据分析定位与既有技能栈选择 Python。
- **为什么重要**：gate 运行时决定 hook 的可执行性；Windows 无 Python 时 hook 警告放行而非硬失败。
- **仓库因此改了什么**：`.githooks/*` 薄入口含 `python` → `py` 回退链；限制记录在 `docs/runbooks.md`。

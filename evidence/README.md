# 规则证据索引

本目录只保存适合进入 Git 的小型验证索引和月度 SHA-256 汇总。完整输入快照、逐规则 trace 和结果由本地 `.artifacts/` 或 GitHub Actions Artifact 保存，不提交到仓库。

- `rules/index.yaml`：规则集最近一次可验证证据的索引模板。
- `monthly/`：按 `YYYY-MM.yaml` 保存 evidence ID、日期、规则版本、Git SHA、状态和 manifest 哈希。

证据文件不能手工修补。任何哈希不一致都应从原 snapshot、规则版本和 Git SHA 重新执行。

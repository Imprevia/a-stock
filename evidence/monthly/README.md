# 月度证据摘要

文件命名为 `YYYY-MM.yaml`，每条记录至少包含：

```yaml
- evidenceId: string
  asOf: YYYY-MM-DD
  ruleSet: market-environment
  ruleSetVersion: 1
  gitSha: string
  status: ok | degraded | insufficient | failed
  manifestSha256: string
```

完整证据包保留在 CI Artifact，不复制到本目录。

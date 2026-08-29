# a-stock

A 股分析与研究工作区。当前已包含市场环境分析看板，后续继续扩展研究模块。

## 这个仓库怎么运作

- `docs/` 是事实源：规格、架构、runbook、执行计划、状态全部落在仓库里，不依赖聊天历史。
- 任何多步工作以 `docs/exec-plans/active/*.md` 起手，完成前回写 Status / 证据 / 缺口。
- 本地 gate 强制"代码改动必须伴随文档更新"：`.githooks/` + `scripts/check-docs-contract.py`。

## 快速开始

```bash
# 1. 安装本地 hooks（git config core.hooksPath .githooks）
python scripts/install-hooks.py

# 2. 手动验证文档契约
python scripts/check-docs-contract.py --mode=full
```

## 市场环境看板

安装 Python 与前端依赖后，分别启动 API 和 Vite：

```bash
python -m pip install -r requirements.txt
python -m uvicorn src.market_environment.api:app --reload --port 8000
npm install --prefix apps/market-environment-dashboard
npm run dev --prefix apps/market-environment-dashboard
```

打开 `http://localhost:5173` 查看上证、深证、创业板、沪深 300 和中证 500 的趋势、区间位置与成交额分析。市场广度指标暂未接入。

## 下一步去哪

- 接手工作 → [docs/status.md](docs/status.md)
- 新任务流程 → [AGENTS.md](AGENTS.md)
- 仓库布局 → [docs/repository-guide.md](docs/repository-guide.md)

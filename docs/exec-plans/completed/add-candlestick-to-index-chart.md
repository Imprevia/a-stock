# 为指数 60 日走势增加 K 线

## Stage（阶段）

历史行情契约扩展与图表升级

## Status（状态）

`completed`

## Scope（范围）

为市场环境看板 01 页面“60 日走势”增加真实日 K 线。后端历史序列补充 `open`、`high`、`low`，前端 ECharts 使用 candlestick 系列展示 OHLC，并保留 MA5/10/20/60 和成交额图。

## Acceptance（验收）

- `/api/market-environment` 的每个历史点包含日期、开盘、收盘、最低、最高、均线和成交额。
- 前端 K 线严格使用真实 OHLC，不用收盘价合成蜡烛。
- MA5/10/20/60 继续叠加在 K 线上，红涨绿跌符合 A 股约定。
- Tooltip 能展示 OHLC 和均线，桌面与 `390px` 移动视口无标签重叠或页面级横向溢出。
- 后端契约测试、前端构建、浏览器 QA 和 docs-contract 完整门禁通过。

## Completion Evidence（完成证据）

- API 历史序列已返回真实 `open` / `high` / `low` / `close`，新增服务契约测试覆盖 OHLC 字段。
- 60 日走势已切换为 ECharts candlestick，并叠加 MA5 / MA10 / MA20 / MA60；红涨绿跌符合 A 股约定。
- Tooltip 已在真实悬停中验证，可同时显示开盘、最高、最低、收盘和四条均线。
- 桌面 `1440 x 900` 与移动 `390 x 844` 浏览器 QA 通过：画布非空，红绿蜡烛像素均存在，无页面级横向溢出，无控制台错误，所有可见文字字号不低于 `14px`。
- `.venv\\Scripts\\python.exe -m pytest tests -q`：`39 passed`，仅保留既有 Starlette/httpx 弃用警告。
- `npm run build`、`git diff --check` 通过；构建仅保留既有大 chunk 提示。
- `SKIP_PLAN_GATE=1 .venv\\Scripts\\python.exe scripts/check-docs-contract.py --mode=full` 通过（代码 6 / 文档 4 / plan 0）；使用逃生口是因为计划已完成并归档，最终工作区不再保留 active plan。

## Remaining Gaps（剩余缺口）

- 无。本次范围已完成。

## Next Step（下一步）

归档到 `docs/exec-plans/completed/`，后续页面沿用现有 K 线色彩、字号和响应式规范。

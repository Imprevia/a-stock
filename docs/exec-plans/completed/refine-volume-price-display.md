# 调整 5 日成交额比值与量价分类展示

## Stage（阶段）

量价口径收紧与指数卡展示调整

## Status（状态）

`completed`

## Scope（范围）

在第 01 页指数卡的量价状态前展示 5 日成交额比值，并移除 `classify_volume_price` 未命中规则时统一返回“量价平稳”的兜底行为。只有满足明确阈值的组合才返回分类；阈值空档保留空分类，前端只展示真实比值。

## Acceptance（验收）

- 指数卡右下角按“5 日成交额比值 + 量价状态”展示，例如 `1.12x 量价平稳`。
- “量价平稳”仅在日涨跌幅绝对值小于 `0.5%` 且 5 日成交额比值位于 `[1.0, 1.2)` 时返回。
- 价格和成交额落在既有分类阈值空档时，`volumePriceState` 返回 `null`，不得兜底为“量价平稳”。
- 缺少有效成交额样本时仍显示 `--` / “数据不足”，不合成比值或分类。
- 后端测试、前端构建、桌面与 `390px` 移动浏览器 QA、docs-contract 完整门禁通过。

## Completion Evidence（完成证据）

- `classify_volume_price` 已取消通用“量价平稳”兜底，仅在日涨跌幅绝对值小于 `0.5%` 且 5 日成交额比值位于 `[1.0, 1.2)` 时返回该状态；其他阈值空档返回 `null`。
- API 契约已允许 `volumePriceState` 为 `null`；真实接口验证中，上证指数为 `1.12x 量价平稳`，其余四个未命中明确规则的指数只返回 5 日比值。
- 指数卡已按“5 日成交额比值 + 可选量价状态”展示，横向比较表对未分类状态显示 `--`。
- `.venv/Scripts/python.exe -m pytest tests -q`：`41 passed`，仅保留既有 Starlette/httpx 弃用警告。
- `npm run build` 通过，仅保留既有大 chunk 提示；`git diff --check` 通过，仅有既有 CRLF 转换提示。
- 浏览器 QA 覆盖 `1440 x 900` 与 `390 x 844`：卡片文字无重叠，移动端真实重载后无页面级横向溢出，所有可见文字不低于 `14px`，控制台无错误。
- `SKIP_PLAN_GATE=1 .venv/Scripts/python.exe scripts/check-docs-contract.py --mode=full` 通过（代码 8 / 文档 5 / plan 0）；使用逃生口是因为新建 active plan 尚未被 Git 跟踪，门禁无法从 `git diff` 识别该文件。

## Remaining Gaps（剩余缺口）

- 无。本次范围已完成。

## Next Step（下一步）

归档到 `docs/exec-plans/completed/`；后续新增量价分类时必须定义明确且互不重叠的价格与成交额阈值，不得恢复兜底分类。

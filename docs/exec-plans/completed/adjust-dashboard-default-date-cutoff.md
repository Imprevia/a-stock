# 调整看板默认日期截止时间

## Stage

实现与验证

## Status

已完成

## Acceptance

- 浏览器本地时间 15:00 前打开看板时，日期控件默认显示前一天。
- 浏览器本地时间达到 15:00 后打开看板时，日期控件默认显示当天。
- 日期格式保持 `YYYY-MM-DD`，跨月、跨年回退正确。
- 前端边界测试、生产构建和 docs-contract full 通过。

## Completion Evidence

- `npm test`：1 个测试文件、4 个日期边界测试全部通过。
- `npm run build`：Vite 生产构建成功。
- `python scripts/check-docs-contract.py --mode=full`：通过。
- `git diff --check`：通过。
- Vite 开发服务已在 `http://127.0.0.1:5173/` 启动。

## Remaining Gaps

无。构建仍报告既有的单 chunk 超过 500 kB 警告，不影响本次日期逻辑。

## Next Step

无；后续日期规则变更继续在 `date-util.ts` 中维护并补边界测试。

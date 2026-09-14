## 1. Planning and contracts

- [x] 1.1 更新产品规格、设计规范、架构、runbook、status，并记录本 change 的验收边界。
- [x] 1.2 新增/更新 OpenSpec specs，定义句式槽位、下一交易日状态与兼容字段。

## 2. Backend contracts and calculations

- [x] 2.1 在 schemas 中新增 `ReviewSentenceSegment`、`ReviewSentence`、`NextSessionComparison` 及嵌套证据类型。
- [x] 2.2 在 calculations 中实现市场级七项证据与结构化句式生成，覆盖完整/部分缺失场景。
- [x] 2.3 在 snapshot store/service 中实现严格下一真实交易日解析和 provider-free 对照计算。
- [x] 2.4 在 API 注册 `/api/market-environment/next-session` GET，保持旧接口响应兼容。
- [x] 2.5 增加计算层、服务层和 API 测试（无 provider 调用、日期一致性、缺失状态）。

## 3. Frontend pages

- [x] 3.1 扩展前端类型与 API client，接入句式和下一日对照数据。
- [x] 3.2 重构第 01 页，保留五指数/两图表并加入七项证据、句式复制、下一日对照和“再学”矩阵。
- [x] 3.3 重排 02–08 页为事实→判断→质量边界，保留 03/04/07 的真实缺失状态。
- [x] 3.4 重构第 09 页综合结论与下一日影响摘要，保留跨页锚点。
- [x] 3.5 移除保存复盘记录、训练进度和相关持久化状态；校验 01–09 hash/路由兼容。
- [x] 3.6 更新样式与响应式断点，确保 1440×900 与 390×844 无页面级横向溢出且文字不小于 14px。
- [x] 3.7 更新并补充前端测试，运行 `npm run test`、`npm run build`。

## 4. Verification and handoff

- [x] 4.1 运行 Python 全量 pytest（或记录环境阻塞）、docs-contract full 和 OpenSpec strict validation。
- [x] 4.2 更新本 change 完成证据、剩余缺口和下一步，汇总验证结果。

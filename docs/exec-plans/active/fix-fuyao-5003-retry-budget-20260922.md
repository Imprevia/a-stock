# 修复扶摇 5003 重试与请求节流

## Stage

客户端稳定性修复与离线验证

## Status

completed-without-production-write

## Acceptance

- 扶摇 limits 专用客户端在连续访问交易日历、代码表和三类池时有最小请求间隔，避免短时间集中请求。
- `HTTP 429`、`code=4001` 和 `code=5003` 使用更慢的有界指数退避；参数、权限和契约错误继续 fail closed，不盲目重试。
- 扶摇错误 warning 只包含业务码、脱敏 message 和 request_id，不包含 API key、请求头或完整响应体。
- 不放宽 exact-date、source revision、membership 完整性或跨日期回填保护；生产数据库写入需另行授权。
- 更新架构和 runbook 中的扶摇请求预算说明，并通过定向 provider 测试与 docs contract。

## Completion Evidence

- 2026-09-22 只读探测确认同一 key、同一 `2026-09-22` 下扶摇交易日历、代码表和三类池当前均返回 `code=0`；三类池观测为涨停 63、炸板 18、跌停 5，说明昨晚 `5003` 更可能是瞬时上游不可用或动态负载。
- 官方文档说明 `HTTP 429` / `code=4001` 需要降低请求频率且避免立即连续重试；`code=5003` 表示数据源不可用、上游失败或响应无法解析。

- `src/market_environment/fuyao.py` 新增 `slow_backoff_seconds`（默认 2.0）和 `_SLOW_RETRY_ENVELOPE_CODES = {4001, 5003}`；HTTP 429 与这两个响应码改走较慢的有界指数退避（`base * 2**attempt`），并把 HTTP 信封错误改为 `HTTP {status} (code=..., message=..., request_id=...)`。参数/权限（`_PERMISSION_CODES = {2001, 2003}`）与契约错误继续 fail closed 不盲目重试，network exception 与 500-599 重试仍走快速退避。
- `FuyaoClient` 在 `_request_data` 中先调用 `_wait_for_request_slot()`：实例级 `threading.Lock` + 单调时钟追踪 `_last_request_started_at`，按 `min_request_interval_seconds`（默认 0.5s）串行节流交易日历、代码表、三类池与分页请求；`min_request_interval_seconds <= 0` 时直接放行，不影响现有测试。
- 错误格式化拆为 `_envelope_error_detail` / `_http_error_detail` / `_safe_text`：strip 控制字符、按 160 字符（request_id 80 字符）截断、强制把 `api_key` 替换为 `<redacted>`；API key、请求头、完整响应体绝不出现在最终 warning/exception 文本里。
- `tests/test_market_environment_fuyao.py` 新增 3 个测试：`test_rate_limit_retry_uses_slow_exponential_backoff` 校验 4001 走 `slow_backoff_seconds` 指数退避（`[1.5, 3.0]`）与脱敏 message/request_id；`test_data_source_unavailable_error_is_auditable_without_secret_echo` 校验 5003 重试 3 次、退避 `[1.25, 2.5]`、且 `fixture-secret` 不出现在异常文本中；`test_requests_are_spaced_by_a_shared_client_interval` 用假时钟校验 6 个请求之间均匀 0.5s 间隔 5 次。
- `docs/architecture.md` 第 53 行（市场环境与涨跌停生态）补充请求节流与脱敏退避的说明；`docs/runbooks.md` 第 315 行（扶摇三类池 runbook）补充客户端节流、退避与脱敏错误格式要求。
- `tests/` 全量 653 passed / 3 skipped（含 `test_market_environment_fuyao.py` 29 全部通过）；`python3 scripts/check-docs-contract.py --mode=full` 通过（代码 2 / 文档 4 / plan 2）。
- 未对生产 CronJob、Pod、PVC、Secret、Helm release 或 NodePort 进行写入；未触发任何真实 provider 调用；未放款 exact-date、source revision、membership 完整性、跨日期回填或失败保留门禁。

## Remaining Gaps

- 生产环境 2026-09-22 的失败 limits task 尚未重试；本计划不进行生产写入。节流与慢退避只降低重复请求压力，真正的恢复仍取决于扶摇按 `as_of=2026-09-22` 回执恢复正常；按 `reactivate-fuyao-scheduled-collection-20260922` 计划，继续观察 2026-09-23 16:30 Asia/Shanghai 的首个自然 trigger。

## Next Step

-若 `2026-09-23 16:30 Asia/Shanghai` 自然触发或后续补采再次出现 `5003`：在短窗口内不再自动重试，而是回到 `failed-retained` 并把 `code=5003, message, request_id` 写入 refreshWarning；恢复后再走 `--refresh` 单项重试 limits dataset。

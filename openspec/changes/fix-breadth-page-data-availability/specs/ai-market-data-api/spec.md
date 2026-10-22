## ADDED Requirements

### Requirement: 历史资源可选参数在 PostgreSQL 上稳定执行
版本化 breadth history 和 limits history 资源 MUST 在省略 `start_date`、`end_date` 或 cursor 时执行有界、确定性的 PostgreSQL 查询，并 MUST 在提供任意合法日期筛选和 continuation cursor 时保持相同的精确日期、排序、分页和 revision 语义。可选参数为 `null` MUST NOT 导致未类型化参数错误或 HTTP 500。

#### Scenario: 首页省略所有可选筛选
- **WHEN** 客户端请求 breadth history 或 limits history，仅提供精确 `as_of` 和合法 `limit`
- **THEN** API 返回 HTTP 200 的有界首页或文档化的 missing/not-found 结果，不返回数据库参数错误，并产生零 provider 调用和零写入

#### Scenario: 首页提供日期范围
- **WHEN** 客户端提供合法 `start_date`、`end_date` 或其中一个边界
- **THEN** API 只返回边界内按日期稳定排序的本地精确日期点位，省略的边界不产生查询错误

#### Scenario: 客户端继续历史分页
- **WHEN** 首页包含 `nextCursor` 且客户端在同一 snapshot revision 下继续请求
- **THEN** 后续页严格从上一页最后日期之后开始，不重复、不遗漏，并保持 provider-free 和 write-free

### Requirement: 渐进迁移客户端隔离子资源失败
使用版本化细粒度资源的 dashboard MUST 将一个页面内的摘要资源和可选历史子资源分别提交到客户端状态。可选历史子资源失败 MUST NOT 使已成功的摘要资源失效，也 MUST NOT 全局关闭同日期其它 V2 资源；只有摘要资源自身失败或稳定 integrity error 才能阻止摘要展示。

#### Scenario: breadth 摘要成功而历史失败
- **WHEN** dashboard 已取得成功的 breadth 摘要，随后 breadth history 返回网络错误或 HTTP 5xx
- **THEN** dashboard 保留并展示摘要，记录历史子资源错误，允许单独重试历史，不回退或覆盖其它已成功的 V2 资源

#### Scenario: breadth 摘要完整性失败
- **WHEN** breadth 摘要返回稳定 `snapshot_integrity_error`
- **THEN** dashboard 不展示该摘要，也不使用 legacy 或其它日期证据替代，并明确呈现数据完整性错误

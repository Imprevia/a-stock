## Purpose

为扶摇市场数据提供可审计的 shadow 差异归因、分页日期证据和行业字段完整性边界，防止正常时间漂移或缺失字段被误判为成功事实。

## ADDED Requirements

### Requirement: Breadth timestamp evidence is date-bound

breadth SHALL accept pagination pages whose raw timestamps differ only when every timestamp maps to the same Shanghai trading date equal to `as_of`; the result MUST retain raw timestamp values and their span.

#### Scenario: Pages have same-date timestamp drift
- **WHEN** all pages report stable `total` and timestamps differ by seconds but map to the requested Shanghai date
- **THEN** breadth is eligible for that date, `timestampExactStable` is false, and raw timestamp evidence is retained

#### Scenario: Pages cross a trading date
- **WHEN** any page timestamp maps to a Shanghai date different from `as_of`
- **THEN** breadth remains insufficient and no successful historical snapshot is written

### Requirement: Core shadow differences are classified

core shadow comparison MUST retain actual value differences and classify them by index, field, date evidence, and provider revision; tolerance changes MUST NOT convert material differences into a match without explicit policy evidence.

#### Scenario: Core providers disagree on values
- **WHEN** both providers cover the same five indices and one or more OHLC/turnover values exceed tolerance
- **THEN** the report is `mismatch` with bounded per-index field differences and the formal snapshot remains unchanged

### Requirement: Sectors completeness is explicit

sectors SHALL only mark the documented four-field fallback capability eligible when code, name, change and turnover are returned by documented endpoints; missing capital-flow, breadth-count or leader-name fields MUST remain null and the report MUST NOT claim a complete sectors replacement.

#### Scenario: Documented endpoint lacks optional enrichment
- **WHEN** industry snapshot provides code, name, change and turnover but no capital-flow, breadth-count or leader field
- **THEN** the payload preserves nulls, reports missing evidence, and remains a documented fallback rather than claiming a complete sectors replacement

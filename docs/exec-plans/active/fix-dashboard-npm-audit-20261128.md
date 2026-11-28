# 修复看板 npm 依赖安全公告

## Stage

前端依赖升级和本地验收完成。

## Status

completed-local-only。

## Acceptance

- 解决部署提交 `8f1ed87` 的 15 条 npm 受影响包记录，复核完整和生产依赖树。
- 使用 Node 22 从更新后的锁文件干净安装，前端 Vitest 和 Vite 构建通过。
- 以浏览器验证 ECharts 的折线、K 线、成交量、tooltip 与板块图表交互。

## Completion Evidence

- 原锁文件使用 npm 官方 registry 复现 3 严重、3 高危、9 中危，生产依赖树为 1 高危、1 中危。
- ECharts 升至 `6.1.0`，Vite `6.4.6`，Vitest `5.1.2`，Happy DOM `21.0.4`，`source-map-js` 锁定为 `1.2.4`。Vitest 改用同一个 Vite，旧 `vite-node` 和 `tinypool` 已从依赖树移除。
- 保留 Vue Test Utils `2.5.0`。针对 `js-beautify 2.0.3` 的两个覆盖项升级 EditorConfig 和 glob，解析至 `minimatch 11.0.9` 和 `brace-expansion 5.1.0`。测试工具的 glob 和 EditorConfig 路径用临时 fixture 验证。
- Node.js `22.22.2` 从锁文件执行 `npm ci` 成功。npm 官方 registry 的完整审计和 `--omit=dev` 审计均为 0 项、退出码 0。
- Vitest 25 个文件、174 项通过。Vite 生产构建通过，保留大包体积提示。Chromium 在 390px 和 1440px 验证价格 K 线与均线、成交额柱图、宽度折线和板块量价图，并确认 tooltip、板块缩放、数据更新、视口变化和实例释放。
- 部署清单和运行手册测试 151 项通过。docs-contract full 和 `git diff --check` 通过。

## Remaining Gaps

- 部署待单独授权。k3s revision 155 仍使用 `8f1ed87` 的前端产物。

## Next Step

获准发布后，使用受控入口构建新镜像并验证线上版本。

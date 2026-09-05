# 修复看板首屏图表初始化

## Stage

Implementation

## Status

in-progress

## Acceptance

- 首次打开或刷新第 01 章时，指数 K 线、成交额图表均创建 ECharts canvas 并显示数据。
- 章节证据异步加载完成后，不会因加载态 DOM 替换而留下空图表容器。
- 切换指数、切换章节、刷新日期和移动端布局不引入图表回归。

## Completion Evidence

- 待补：前端测试、生产构建和浏览器截图/画布检查。

## Remaining Gaps

- 尚未完成回归验证。

## Next Step

- 补充针对章节加载结束重绘的测试，运行构建并用浏览器确认两个图表均有 canvas 和非空像素。

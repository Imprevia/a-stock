/**
 * useChartLifecycle — owns the echarts lifecycle for one DOM element. The
 * composable initialises an echarts instance on mount, applies an option
 * computed from the passed factory, watches a list of reactive sources for
 * redraws, resizes on window resize, and disposes on unmount. Callers must
 * NOT keep a reference to the returned instance — the composable owns it.
 */
import { onBeforeUnmount, onMounted, watch, type Ref } from 'vue'
import * as echarts from 'echarts'

export interface ChartLifecycle {
  resize(): void
  dispose(): void
}

export function useChartLifecycle(
  elementRef: Ref<HTMLElement | null>,
  optionFactory: () => echarts.EChartsOption,
  watchSources?: () => unknown,
): ChartLifecycle {
  let chart: echarts.ECharts | null = null

  function applyOption(): void {
    if (!chart) return
    chart.setOption(optionFactory(), { notMerge: true })
  }

  function resize(): void {
    chart?.resize()
  }

  function dispose(): void {
    if (!chart) return
    chart.dispose()
    chart = null
  }

  function handleResize(): void {
    resize()
  }

  onMounted(() => {
    if (!elementRef.value) return
    chart = echarts.init(elementRef.value)
    applyOption()
    window.addEventListener('resize', handleResize)
  })

  if (watchSources) {
    watch(watchSources, () => {
      applyOption()
    })
  }

  onBeforeUnmount(() => {
    window.removeEventListener('resize', handleResize)
    dispose()
  })

  return { resize, dispose }
}
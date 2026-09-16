<script setup lang="ts">
/**
 * IndexPriceChartPanel — K 线 + MA5/10/20/60 折线。
 *
 * Owns one echarts instance via useChartLifecycle; receives `history`
 * (IndexAnalysis.history entries with date/open/close/low/high/ma*)
 * and `dates` (precomputed date labels) from the parent so the panel
 * stays a thin shell around the composable. Redraws on
 * props.history change.
 */
import { computed, ref } from 'vue'
import type { HistoryPoint } from '../../types'
import { useChartLifecycle } from '../../composables/useChartLifecycle'

interface TooltipItem {
  axisValueLabel?: string
  data?: number[] | null
  marker?: string
  seriesName?: string
  value?: number | number[] | null
}

const props = defineProps<{
  history: HistoryPoint[]
  dates: string[]
  source: string
}>()

const chartElement = ref<HTMLElement | null>(null)

function formatPriceTooltip(params: unknown): string {
  const items = Array.isArray(params) ? params as TooltipItem[] : []
  const candle = items.find((item) => item.seriesName === 'K线')
  const rawValues = Array.isArray(candle?.data) ? candle.data : Array.isArray(candle?.value) ? candle.value : []
  const values = rawValues.length === 5 ? rawValues.slice(1) : rawValues
  const [open, close, low, high] = values.map((value) => Number(value))
  const lines = [`<strong>${items[0]?.axisValueLabel ?? ''}</strong>`]
  if (values.length === 4) {
    lines.push(`${candle?.marker ?? ''}开 ${open.toFixed(2)}　高 ${high.toFixed(2)}`)
    lines.push(`收 ${close.toFixed(2)}　低 ${low.toFixed(2)}`)
  }
  for (const item of items.filter((entry) => entry.seriesName?.startsWith('MA'))) {
    const value = typeof item.value === 'number' ? item.value : null
    if (value != null) lines.push(`${item.marker ?? ''}${item.seriesName}　${value.toFixed(2)}`)
  }
  return lines.join('<br/>')
}

const option = computed(() => ({
  animation: false,
  grid: { top: 28, right: 18, bottom: 42, left: 62 },
  tooltip: { trigger: 'axis', confine: true, textStyle: { fontSize: 14 }, formatter: formatPriceTooltip },
  legend: { top: 0, right: 0, itemWidth: 14, itemHeight: 8, textStyle: { color: '#68727e', fontSize: 14 } },
  xAxis: {
    type: 'category',
    data: props.dates,
    boundaryGap: true,
    axisLabel: { color: '#8a939e', fontSize: 14 },
    axisLine: { lineStyle: { color: '#dfe4e8' } },
  },
  yAxis: {
    type: 'value',
    scale: true,
    axisLabel: { color: '#8a939e', fontSize: 14 },
    splitLine: { lineStyle: { color: '#edf0f2' } },
  },
  series: [
    {
      name: 'K线',
      type: 'candlestick',
      data: props.history.map((item) => [item.open, item.close, item.low, item.high]),
      itemStyle: { color: '#c65050', color0: '#26815f', borderColor: '#c65050', borderColor0: '#26815f' },
    },
    { name: 'MA5', type: 'line', data: props.history.map((item) => item.ma5), showSymbol: false, connectNulls: false, lineStyle: { width: 1.2, color: '#c45b55' }, z: 3 },
    { name: 'MA10', type: 'line', data: props.history.map((item) => item.ma10), showSymbol: false, connectNulls: false, lineStyle: { width: 1.2, color: '#7263a7' }, z: 3 },
    { name: 'MA20', type: 'line', data: props.history.map((item) => item.ma20), showSymbol: false, connectNulls: false, lineStyle: { width: 1.5, color: '#d18a35' }, z: 3 },
    { name: 'MA60', type: 'line', data: props.history.map((item) => item.ma60), showSymbol: false, connectNulls: false, lineStyle: { width: 1.5, color: '#87929d' }, z: 3 },
  ],
}))

useChartLifecycle(
  chartElement,
  () => option.value as unknown as Record<string, unknown>,
  () => [props.history, props.dates],
)
</script>

<template>
  <div ref="chartElement" class="price-chart" />
</template>
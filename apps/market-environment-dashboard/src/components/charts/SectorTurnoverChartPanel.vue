<script setup lang="ts">
import { computed, ref } from 'vue'

import { useChartLifecycle } from '../../composables/useChartLifecycle'
import type { ThsSectorBar } from '../../types'

interface TooltipItem {
  axisValueLabel?: string
  marker?: string
  seriesName?: string
  data?: number[] | number | null
  value?: number[] | number | null
}

const props = defineProps<{
  bars: ThsSectorBar[]
}>()

const chartElement = ref<HTMLElement | null>(null)

const dates = computed(() => props.bars.map((item) => item.tradingDate))

function compactNumber(value: number | null | undefined): string {
  if (value == null) return '--'
  if (Math.abs(value) >= 100000000) return `${(value / 100000000).toFixed(1)} 亿`
  if (Math.abs(value) >= 10000) return `${(value / 10000).toFixed(1)} 万`
  return value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function tooltipFormatter(params: unknown): string {
  const items = Array.isArray(params) ? params as TooltipItem[] : []
  const candle = items.find((item) => item.seriesName === '板块 K 线')
  const raw = Array.isArray(candle?.data) ? candle.data : Array.isArray(candle?.value) ? candle.value : []
  const values = raw.length === 5 ? raw.slice(1) : raw
  const [open, close, low, high] = values.map((value) => Number(value))
  const lines = [`<strong>${items[0]?.axisValueLabel ?? ''}</strong>`]
  if (values.length === 4 && values.every(Number.isFinite)) {
    lines.push(`${candle?.marker ?? ''}开 ${open.toFixed(2)}　高 ${high.toFixed(2)}`)
    lines.push(`收 ${close.toFixed(2)}　低 ${low.toFixed(2)}`)
  }
  for (const name of ['成交量', '成交额']) {
    const item = items.find((entry) => entry.seriesName === name)
    const value = typeof item?.value === 'number' ? item.value : typeof item?.data === 'number' ? item.data : null
    lines.push(`${item?.marker ?? ''}${name} ${compactNumber(value)}`)
  }
  return lines.join('<br/>')
}

const option = computed(() => ({
  animation: false,
  legend: {
    top: 0,
    right: 8,
    data: ['板块 K 线', '成交量', '成交额'],
    itemWidth: 14,
    itemHeight: 9,
    textStyle: { color: '#68736e', fontSize: 14 },
  },
  tooltip: {
    trigger: 'axis',
    confine: true,
    axisPointer: { type: 'cross' },
    textStyle: { fontSize: 14 },
    formatter: tooltipFormatter,
  },
  axisPointer: { link: [{ xAxisIndex: 'all' }] },
  grid: [
    { left: 70, right: 24, top: 40, height: '48%' },
    { left: 70, right: 24, top: '61%', height: '13%' },
    { left: 70, right: 24, top: '79%', height: '13%' },
  ],
  xAxis: [0, 1, 2].map((index) => ({
    type: 'category',
    gridIndex: index,
    data: dates.value,
    boundaryGap: true,
    axisLine: { lineStyle: { color: '#dfe6e2' } },
    axisLabel: { show: index === 2, color: '#7e8a85', fontSize: 14, hideOverlap: true },
    axisTick: { show: false },
  })),
  yAxis: [
    {
      type: 'value', gridIndex: 0, scale: true,
      axisLabel: { color: '#7e8a85', fontSize: 14 },
      splitLine: { lineStyle: { color: '#eef2f0' } },
    },
    {
      type: 'value', gridIndex: 1, scale: true, splitNumber: 2,
      axisLabel: { color: '#7e8a85', fontSize: 14, formatter: compactNumber },
      splitLine: { lineStyle: { color: '#f1f4f2' } },
    },
    {
      type: 'value', gridIndex: 2, scale: true, splitNumber: 2,
      axisLabel: { color: '#7e8a85', fontSize: 14, formatter: compactNumber },
      splitLine: { lineStyle: { color: '#f1f4f2' } },
    },
  ],
  dataZoom: [
    { type: 'inside', xAxisIndex: [0, 1, 2], start: Math.max(0, 100 - (80 / Math.max(props.bars.length, 1)) * 100), end: 100 },
    { type: 'slider', xAxisIndex: [0, 1, 2], bottom: 0, height: 20, textStyle: { fontSize: 14 } },
  ],
  series: [
    {
      name: '板块 K 线', type: 'candlestick', xAxisIndex: 0, yAxisIndex: 0,
      data: props.bars.map((item) => [item.open, item.close, item.low, item.high]),
      itemStyle: { color: '#c65050', color0: '#26815f', borderColor: '#c65050', borderColor0: '#26815f' },
    },
    {
      name: '成交量', type: 'bar', xAxisIndex: 1, yAxisIndex: 1,
      data: props.bars.map((item) => item.volume), barMaxWidth: 10,
      itemStyle: { color: '#78a5a0' },
    },
    {
      name: '成交额', type: 'bar', xAxisIndex: 2, yAxisIndex: 2,
      data: props.bars.map((item) => item.turnover), barMaxWidth: 10,
      itemStyle: { color: '#c3a15f' },
    },
  ],
}))

useChartLifecycle(
  chartElement,
  () => option.value,
  () => [props.bars],
)
</script>

<template>
  <div ref="chartElement" class="sector-turnover-chart" aria-label="板块蜡烛图、成交量和成交额" />
</template>

<script setup lang="ts">
/**
 * BreadthHistoryChartPanel — 近 5 日宽度趋势折线图。
 *
 * Owns one echarts instance via useChartLifecycle. Renders advanceRatio
 * and medianReturn as two series on dual axes, with the current trading
 * day marker pushed on top of the historical points.
 */
import { computed, ref } from 'vue'
import { useChartLifecycle } from '../../composables/useChartLifecycle'

interface BreadthPoint {
  asOf: string
  advanceRatio: number | null
  medianReturn: number | null
}

const props = defineProps<{
  points: BreadthPoint[]
  asOf: string
  advanceRatio: number | null
  medianReturn: number | null
}>()

const chartElement = ref<HTMLElement | null>(null)

const dates = computed(() => props.points.map((row) => row.asOf.slice(5)))
const advanceSeries = computed(() => props.points.map((row) => row.advanceRatio == null ? null : Number((row.advanceRatio * 100).toFixed(2))))
const medianSeries = computed(() => props.points.map((row) => row.medianReturn == null ? null : Number(row.medianReturn.toFixed(2))))

const option = computed(() => {
  const localDates = [...dates.value]
  const localAdvance = [...advanceSeries.value]
  const localMedian = [...medianSeries.value]
  if (props.advanceRatio != null && !localAdvance.length) localAdvance.push(Number((props.advanceRatio * 100).toFixed(2)))
  if (props.medianReturn != null && !localMedian.length) localMedian.push(Number(props.medianReturn.toFixed(2)))
  const todayLabel = props.asOf.slice(5)
  if (todayLabel && !localDates.includes(todayLabel)) localDates.push(todayLabel)
  return {
    animation: false,
    grid: { top: 32, right: 56, bottom: 36, left: 56 },
    legend: { top: 0, left: 0, textStyle: { color: '#68727e', fontSize: 14 } },
    tooltip: { trigger: 'axis', confine: true, textStyle: { fontSize: 14 } },
    xAxis: {
      type: 'category',
      data: localDates,
      boundaryGap: true,
      axisLabel: { color: '#8a939e', fontSize: 14 },
      axisLine: { lineStyle: { color: '#dfe4e8' } },
    },
    yAxis: [
      {
        type: 'value',
        name: '上涨占比 %',
        nameTextStyle: { color: '#4f5b56', fontSize: 13 },
        axisLabel: { color: '#8a939e', fontSize: 14 },
        splitLine: { lineStyle: { color: '#edf0f2' } },
      },
      {
        type: 'value',
        name: '中位数 %',
        nameTextStyle: { color: '#4f5b56', fontSize: 13 },
        axisLabel: { color: '#8a939e', fontSize: 14 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: '上涨占比',
        type: 'line',
        data: localAdvance,
        showSymbol: true,
        symbolSize: 8,
        lineStyle: { width: 2, color: '#257153' },
        itemStyle: { color: '#257153' },
      },
      {
        name: '涨跌幅中位数',
        type: 'line',
        yAxisIndex: 1,
        data: localMedian,
        showSymbol: true,
        symbolSize: 8,
        lineStyle: { width: 2, color: '#c45b55' },
        itemStyle: { color: '#c45b55' },
      },
    ],
  }
})

useChartLifecycle(
  chartElement,
  () => option.value as unknown as Record<string, unknown>,
  () => [props.points, props.asOf, props.advanceRatio, props.medianReturn],
)
</script>

<template>
  <div ref="chartElement" class="breadth-history-chart" aria-label="近 5 日宽度趋势折线" />
</template>
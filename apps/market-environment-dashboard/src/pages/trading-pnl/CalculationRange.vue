<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { calculationQuery, calculationRequest, errorMessage, issueLabel, type CalculationResult } from '../../trading-pnl'

const props = defineProps<{ month: string; date?: string; refreshToken: number }>()
const route = useRoute()
const range = computed(() => calculationQuery(route.query))
const result = ref<CalculationResult | null>(null)
const error = ref('')
const startMonth = computed(() => range.value.start?.slice(0, 7))
const endMonth = computed(() => range.value.end?.slice(0, 7))
const missing = computed(() => result.value?.missing.filter(item => !props.date || item.date === props.date) ?? [])

watch([() => range.value.start && range.value.end ? range.value.batch : undefined, () => props.refreshToken], async ([batch], _, onCleanup) => {
  result.value = null
  error.value = ''
  if (!batch) return
  let stale = false
  onCleanup(() => { stale = true })
  try {
    const latest = await calculationRequest(batch)
    if (!stale) result.value = latest
  } catch (reason) {
    if (!stale) error.value = errorMessage(reason)
  }
}, { immediate: true })
</script>

<template>
  <section v-if="range.start && range.end" class="pnl-panel" aria-labelledby="pnl-calculation-title">
    <h2 id="pnl-calculation-title">计算范围</h2>
    <p>{{ range.start }} 至 {{ range.end }}</p>
    <p v-if="result?.status === 'partial'" role="status">已完成部分计算，剩余缺项可重试。</p>
    <p v-if="error" class="pnl-muted" role="status">无法读取本批缺项摘要。{{ error }}</p>
    <nav v-if="!date" class="pnl-inline" aria-label="计算结果导航">
      <RouterLink v-if="startMonth !== month" class="pnl-back" :to="{ name: 'trading-pnl-calendar', query: { ...range, month: startMonth } }">查看起始月</RouterLink>
      <RouterLink v-if="endMonth !== month" class="pnl-back" :to="{ name: 'trading-pnl-calendar', query: { ...range, month: endMonth } }">查看结束月</RouterLink>
      <RouterLink v-if="result?.status === 'partial' || result?.status === 'retry'" class="pnl-back"
        :to="{ name: 'trading-pnl-import', query: { ...range, month } }">返回入账结果以重试</RouterLink>
    </nav>
    <details v-if="missing.length" open>
      <summary>{{ date ? '当日计算缺项' : '计算缺项' }}（{{ missing.length }} 项）</summary>
      <ul class="pnl-issues">
        <li v-for="(item, index) in missing" :key="index">
          <RouterLink v-if="!date" class="pnl-back"
            :to="{ name: 'trading-pnl-day', params: { date: item.date }, query: { ...range, month } }">{{ item.date }}</RouterLink>
          <template v-else>{{ item.date }}</template>
          <template v-if="item.security"> · {{ item.security }}</template> · {{ issueLabel(item.reason) }}
        </li>
      </ul>
    </details>
  </section>
</template>

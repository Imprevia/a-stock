<script setup lang="ts">
/**
 * Document07EventsPage — 第 07 章 公告、政策、外围和事件（事件台账）。
 *
 * Extracted from App.vue's inline `v-else-if="selectedDocumentId === '07'"`
 * block in Phase B-07 of frontend-component-split. Data comes from the
 * core payload's chapter01.events — no section prefetch needed. Event
 * timestamps render via the pure formatDateTime with the store's
 * effectiveTimeZone passed explicitly.
 */
import { FileCheck2 } from 'lucide-vue-next'
import { computed } from 'vue'

import { formatDateTime as fmtDateTime, formatDateTimeTitle } from '../../composables/useFormatDateTime'
import { useDocumentContext } from '../../composables/useDocumentContext'
import { useMarketStore } from '../../stores/market'
import { usePreferencesStore } from '../../stores/preferences'

const market = useMarketStore()
const ctx = useDocumentContext()
const preferences = usePreferencesStore()

const events = computed(() => market.chapter?.events)
const items = computed(() => events.value?.items ?? [])

function formatEventTime(value: string | null | undefined): string {
  return fmtDateTime(value, { timeZone: preferences.effectiveTimeZone })
}
</script>

<template>
  <p class="page-flow-label">事实 → 判断 → 质量边界</p>

  <section class="two-column-grid">
    <article class="panel analysis-panel">
      <div class="panel-heading">
        <div><span class="panel-kicker">事件台账</span><h2>{{ events?.state || '未核实' }}</h2></div>
        <span class="quality-badge" :class="ctx.qualityTone(events?.quality)">{{ ctx.qualityLabel(events?.quality) }}</span>
      </div>
      <div v-if="items.length" class="event-list">
        <article v-for="event in items" :key="`${event.title}-${event.publishedAt}`">
          <FileCheck2 :size="18" />
          <div>
            <strong>{{ event.title }}</strong>
            <span :title="formatDateTimeTitle(event.publishedAt)">
              {{ event.source || '来源未标注' }} · {{ event.publishedAt ? formatEventTime(event.publishedAt) : '时间未标注' }}
            </span>
          </div>
          <em :class="event.verified ? 'verified' : ''">{{ event.verified ? '已核实' : '待核实' }}</em>
        </article>
      </div>
      <div v-else class="empty-evidence">
        <FileCheck2 :size="24" />
        <strong>没有可追溯事件输入</strong>
        <p>{{ events?.quality.warning || '事件不直接决定市场环境；未核实传闻不得进入加分。' }}</p>
      </div>
    </article>
    <article class="panel rule-panel">
      <div class="panel-heading">
        <div><span class="panel-kicker">调整边界</span><h2>盘面确认后最多 ±5 分</h2></div>
      </div>
      <p>来源可靠性、信息新鲜度、价格成交确认、板块扩散和次日承接必须分开记录。</p>
    </article>
  </section>
</template>
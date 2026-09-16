<script setup lang="ts">
/**
 * Phase 1 placeholder for the dashboard route. Replaced in Phase 2 by
 * DashboardLayout.vue with a nested <RouterView/>.
 */
defineProps<{ documentId?: string }>()
</script>

<template>
  <section class="state-panel">
    <h2>Dashboard 章节占位</h2>
    <p>Phase 1 占位组件，Phase 2 将由 DashboardLayout 替换。documentId={{ documentId ?? '--' }}</p>
  </section>
</template>
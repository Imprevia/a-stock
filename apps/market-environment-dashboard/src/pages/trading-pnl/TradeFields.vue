<script setup lang="ts">
import { statusLabel, type TradeFields } from '../../trading-pnl'

const fields = defineModel<TradeFields>({ required: true })

const mainInputs = [
  { key: 'date', label: '交易日期', type: 'date' },
  { key: 'security', label: '证券代码', type: 'text' },
  { key: 'name', label: '证券名称', type: 'text' },
  { key: 'filled_quantity', label: '实际成交股数', type: 'number', step: '1' },
  { key: 'price', label: '成交单价', type: 'number', step: '0.000001' },
  { key: 'amount', label: '成交额', type: 'number', step: '0.01' },
]
const reviewInputs = [
  { key: 'ordered_quantity', label: '委托股数', type: 'number', step: '1' },
  { key: 'time', label: '成交或委托时间', type: 'time' },
  { key: 'order_id', label: '委托关联编号', type: 'text' },
  { key: 'trade_id', label: '成交编号', type: 'text' },
  { key: 'event_id', label: '委托状态事件编号', type: 'text' },
  { key: 'commission', label: '实际佣金', type: 'number', step: '0.01' },
  { key: 'other_fees', label: '其他费用', type: 'number', step: '0.01' },
]

function read(key: string): string {
  return String(fields.value[key] ?? '')
}

function update(key: string, event: Event): void {
  const target = event.target as HTMLInputElement
  const value = key === 'security' ? target.value.toUpperCase().trim() : target.value
  const empty = ['date', 'security', 'name', 'side', 'status'].includes(key) ? '' : null
  fields.value = { ...fields.value, [key]: target.type === 'checkbox' ? target.checked : value || empty }
}
</script>

<template>
  <div class="pnl-fields">
    <label v-for="input in mainInputs" :key="input.key">
      {{ input.label }}
      <input :type="input.type" :step="input.step" :min="input.type === 'number' ? 0 : undefined"
        :value="read(input.key)" @input="update(input.key, $event)" />
    </label>
    <label>方向
      <select :value="read('side')" @change="update('side', $event)">
        <option value="">待核对</option><option value="buy">买入</option><option value="sell">卖出</option>
      </select>
    </label>
    <label>状态
      <select :value="read('status')" @change="update('status', $event)">
        <option value="">待核对</option>
        <option v-for="status in ['filled', 'partial', 'pending', 'canceled']" :key="status" :value="status">{{ statusLabel(status) }}</option>
      </select>
    </label>
  </div>
  <details class="pnl-trade-extra">
    <summary>委托、编号和费用</summary>
    <div class="pnl-fields">
      <label v-for="input in reviewInputs" :key="input.key">
        {{ input.label }}
        <input :type="input.type" :step="input.step" :min="input.type === 'number' ? 0 : undefined"
          :value="read(input.key)" @input="update(input.key, $event)" />
      </label>
      <label class="pnl-check"><input type="checkbox" :checked="!!fields.cumulative" @change="update('cumulative', $event)" /> 委托累计成交</label>
      <label class="pnl-check"><input type="checkbox" :checked="!!fields.fees_pending" @change="update('fees_pending', $event)" /> 另有费用待核</label>
    </div>
  </details>
</template>

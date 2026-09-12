<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Check, CircleAlert, Globe2, Save } from 'lucide-vue-next'
import {
  formatDateTime,
  formatDateTimeTitle,
  getCurrentUtcIso,
  getBrowserTimeZone,
  isSupportedTimeZone,
  saveTimezonePreference,
  timezonePreferences,
  timezoneSourceLabel,
} from './timezone'

const personalTimeZone = ref(timezonePreferences.personalTimeZone ?? '')
const workspaceTimeZone = ref(timezonePreferences.workspaceTimeZone ?? '')
const status = ref<{ kind: 'success' | 'info' | 'error'; message: string } | null>(null)
const savingScope = ref<'personal' | 'workspace' | null>(null)

const browserTimeZone = computed(() => getBrowserTimeZone() ?? 'UTC')
const effectiveTimeZone = computed(() => timezonePreferences.effectiveTimeZone)
const effectiveSource = computed(() => timezoneSourceLabel(timezonePreferences.source))
const previewIso = ref(getCurrentUtcIso())
const preview = computed(() => formatDateTime(previewIso.value, { precision: 'second', timeZone: effectiveTimeZone.value }))
const personalInvalid = computed(() => Boolean(personalTimeZone.value && !isSupportedTimeZone(personalTimeZone.value)))
const workspaceInvalid = computed(() => Boolean(workspaceTimeZone.value && !isSupportedTimeZone(workspaceTimeZone.value)))

watch(() => timezonePreferences.personalTimeZone, (value) => {
  if (savingScope.value === null) personalTimeZone.value = value ?? ''
})
watch(() => timezonePreferences.workspaceTimeZone, (value) => {
  if (savingScope.value === null) workspaceTimeZone.value = value ?? ''
})

const commonTimeZones = [
  'UTC', 'Asia/Shanghai', 'Asia/Hong_Kong', 'Asia/Tokyo', 'Asia/Singapore',
  'Asia/Kolkata', 'Europe/London', 'Europe/Berlin', 'America/New_York',
  'America/Los_Angeles', 'America/Chicago', 'Australia/Sydney',
]
const timeZoneOptions = computed(() => {
  const supportedValuesOf = (Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf
  const all = supportedValuesOf ? supportedValuesOf('timeZone') : commonTimeZones
  return [...new Set(['UTC', browserTimeZone.value, ...commonTimeZones, ...all])].sort((a, b) => a.localeCompare(b))
})

async function save(scope: 'personal' | 'workspace') {
  const value = scope === 'personal' ? personalTimeZone.value : workspaceTimeZone.value
  if (value && !isSupportedTimeZone(value)) {
    status.value = { kind: 'error', message: '请输入受支持的 IANA 时区，例如 Asia/Shanghai。' }
    return
  }
  savingScope.value = scope
  status.value = null
  const result = await saveTimezonePreference(scope, value || null)
  savingScope.value = null
  status.value = { kind: result.kind, message: result.message }
  if (result.ok) {
    personalTimeZone.value = timezonePreferences.personalTimeZone ?? ''
    workspaceTimeZone.value = timezonePreferences.workspaceTimeZone ?? ''
  }
}
</script>

<template>
  <section class="settings-page" aria-labelledby="timezone-settings-title">
    <header class="settings-header">
      <div>
        <span>偏好设置</span>
        <h1 id="timezone-settings-title">日期与时间</h1>
        <p>所有时间保留原始 UTC，可按生效时区阅读。</p>
      </div>
      <Globe2 :size="28" aria-hidden="true" />
    </header>

    <section class="timezone-effective-card" aria-live="polite">
      <div>
        <span class="panel-kicker">当前生效时区</span>
        <strong>{{ effectiveTimeZone }}</strong>
        <small>来源：{{ effectiveSource }} · 浏览器：{{ browserTimeZone }}</small>
      </div>
      <time :datetime="previewIso" :title="formatDateTimeTitle(previewIso)">{{ preview }}</time>
    </section>
    <div v-if="timezonePreferences.loading" class="settings-status info" role="status">正在读取个人与工作区时区偏好…</div>
    <div v-else-if="timezonePreferences.warning" class="settings-status info" role="status"><CircleAlert :size="18" /><span>{{ timezonePreferences.warning }}</span></div>

    <section class="settings-card">
      <div class="settings-card-heading">
        <div><span class="panel-kicker">个人设置</span><h2>个人时区</h2></div>
        <span>优先于工作区设置</span>
      </div>
      <label class="settings-field">
        <span>IANA 时区</span>
        <input v-model="personalTimeZone" list="iana-time-zones" placeholder="留空以跟随下一级偏好" :aria-invalid="personalInvalid" />
      </label>
      <p class="settings-hint">例如 Asia/Shanghai、America/New_York。留空会使用工作区或浏览器时区。</p>
      <p v-if="personalInvalid" class="settings-validation" role="alert">请输入受支持的 IANA 时区，例如 Asia/Shanghai。</p>
      <button class="command-button settings-save" type="button" :disabled="savingScope !== null || personalInvalid" @click="save('personal')">
        <Save :size="16" />
        <span>{{ savingScope === 'personal' ? '保存中…' : '保存个人时区' }}</span>
      </button>
    </section>

    <section class="settings-card">
      <div class="settings-card-heading">
        <div><span class="panel-kicker">工作区设置</span><h2>工作区时区</h2></div>
        <span>{{ timezonePreferences.canManageWorkspaceTimeZone ? '管理员可修改' : '需要管理员权限' }}</span>
      </div>
      <label class="settings-field">
        <span>IANA 时区</span>
        <input v-model="workspaceTimeZone" list="iana-time-zones" placeholder="未设置" :disabled="!timezonePreferences.canManageWorkspaceTimeZone" :aria-invalid="workspaceInvalid" />
      </label>
      <p class="settings-hint">个人未设置时，工作区时区会作为团队默认值。</p>
      <p v-if="workspaceInvalid" class="settings-validation" role="alert">请输入受支持的 IANA 时区，例如 Asia/Shanghai。</p>
      <p v-else-if="!timezonePreferences.canManageWorkspaceTimeZone" class="settings-validation" role="status">当前账号没有修改工作区时区的权限。</p>
      <button class="command-button settings-save" type="button" :disabled="savingScope !== null || !timezonePreferences.canManageWorkspaceTimeZone || workspaceInvalid" @click="save('workspace')">
        <Save :size="16" />
        <span>{{ savingScope === 'workspace' ? '保存中…' : '保存工作区时区' }}</span>
      </button>
    </section>

    <div v-if="status" class="settings-status" :class="status.kind" :role="status.kind === 'error' ? 'alert' : 'status'">
      <CircleAlert v-if="status.kind === 'error'" :size="18" />
      <Check v-else :size="18" />
      <span>{{ status.message }}</span>
    </div>

    <datalist id="iana-time-zones">
      <option v-for="item in timeZoneOptions" :key="item" :value="item" />
    </datalist>
  </section>
</template>

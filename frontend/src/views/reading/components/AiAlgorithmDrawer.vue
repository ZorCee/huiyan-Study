<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ReadingApi } from '@/api'
import type { AiAlgorithmCatalog, AiAlgorithmItem, AiAlgorithmKey, AiRunResult } from '@/api/reading'
import { lesionColor, lesionName } from '@/utils/lesion-colors'

type RunState = 'idle' | 'queued' | 'running' | 'done' | 'failed' | 'not_deployed'

const props = defineProps<{
  modelValue: boolean
  caseId: number | null
  imageUrl: string
  eye?: string
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'overlay', payload: { url: string; name: string }): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v)
})

const catalog = ref<AiAlgorithmCatalog | null>(null)
const catalogLoading = ref(false)
const catalogError = ref('')
const selected = ref<AiAlgorithmKey[]>([])
const running = ref(false)
const states = reactive<Record<string, RunState>>({})
const results = reactive<Record<string, AiRunResult | null>>({})
const errors = reactive<Record<string, string>>({})
const activeOverlay = ref('')

const items = computed<AiAlgorithmItem[]>(() => catalog.value?.items || [])

const STATUS_TEXT: Record<string, { text: string; type: 'success' | 'info' | 'warning' | 'danger' }> = {
  available: { text: '可用', type: 'success' },
  not_deployed: { text: '未部署', type: 'info' },
  unreachable: { text: '连不上', type: 'danger' }
}
const RUN_TEXT: Record<RunState, string> = {
  idle: '',
  queued: '排队中',
  running: '计算中',
  done: '完成',
  failed: '失败',
  not_deployed: '未部署'
}

const loadCatalog = async () => {
  catalogLoading.value = true
  catalogError.value = ''
  try {
    catalog.value = await ReadingApi.getAiAlgorithms()
    if (!selected.value.length) {
      selected.value = items.value.filter((i) => i.status === 'available').map((i) => i.key)
    }
  } catch (err: any) {
    catalogError.value = err?.message || '算法目录加载失败'
  } finally {
    catalogLoading.value = false
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open && !catalog.value && !catalogLoading.value) loadCatalog()
  },
  { immediate: true }
)

watch(
  () => props.imageUrl,
  () => {
    for (const key of Object.keys(states)) {
      states[key] = 'idle'
      results[key] = null
      errors[key] = ''
    }
    activeOverlay.value = ''
  }
)

const toggle = (key: AiAlgorithmKey, checked: boolean) => {
  selected.value = checked ? [...selected.value, key] : selected.value.filter((k) => k !== key)
}

const showOverlay = (result: AiRunResult) => {
  if (!result.overlayUrl) return
  activeOverlay.value = result.algorithm
  emit('overlay', { url: result.overlayUrl, name: result.algorithmName })
}

const runSelected = async () => {
  if (!props.caseId || !props.imageUrl || !selected.value.length) return
  const queue = items.value.filter((i) => selected.value.includes(i.key))
  running.value = true
  for (const item of queue) {
    states[item.key] = 'queued'
    results[item.key] = null
    errors[item.key] = ''
  }
  for (const item of queue) {
    states[item.key] = 'running'
    try {
      const res = await ReadingApi.runAiAlgorithm(props.caseId, {
        algorithm: item.key,
        imageUrl: props.imageUrl,
        eye: props.eye && props.eye !== 'UNKNOWN' ? props.eye : undefined
      })
      results[item.key] = res
      states[item.key] = res.status
      if (res.status === 'done' && res.overlayUrl) showOverlay(res)
    } catch (err: any) {
      states[item.key] = 'failed'
      errors[item.key] = err?.message || `${item.name}调用失败`
    }
  }
  running.value = false
}

const probabilityRows = (r: AiRunResult) =>
  Object.entries(r.classification?.probabilities || {})
    .map(([label, value]) => ({ label, pct: Math.round(Number(value) * 1000) / 10 }))
    .sort((a, b) => b.pct - a.pct)

const formatCdr = (v: number | null | undefined) => (v === null || v === undefined ? '—' : v.toFixed(2))
</script>

<template>
  <el-drawer v-model="visible" title="AI算法判读" size="440px" class="ai-algo-drawer">
    <div class="ai-drawer-body">
      <p class="ai-intro">
        对当前这张眼底图运行算法，结果只用于带教参考，不写入阅片记录、不影响评分。
      </p>

      <el-alert
        v-if="catalog && !catalog.reachable"
        type="error"
        :closable="false"
        show-icon
        :title="catalog.message || '算法服务器暂时连不上'"
      />
      <el-alert v-if="catalogError" type="error" :closable="false" show-icon :title="catalogError" />

      <div v-if="catalogLoading" class="ai-loading">正在读取算法目录…</div>

      <ul v-else class="ai-list">
        <li v-for="item in items" :key="item.key" class="ai-item" :class="{ disabled: item.status !== 'available' }">
          <div class="ai-item-head">
            <el-checkbox
              :model-value="selected.includes(item.key)"
              :disabled="item.status !== 'available' || running"
              @change="(v: any) => toggle(item.key, !!v)"
            >
              <span class="ai-item-name">{{ item.name }}</span>
            </el-checkbox>
            <div class="ai-item-tags">
              <el-tag v-if="item.teacherOnly" size="small" type="warning" effect="plain">仅带教</el-tag>
              <el-tag size="small" :type="STATUS_TEXT[item.status]?.type || 'info'" effect="light">
                {{ STATUS_TEXT[item.status]?.text || item.status }}
              </el-tag>
            </div>
          </div>
          <dl class="ai-meta">
            <div><dt>模型</dt><dd>{{ item.model }}</dd></div>
            <div><dt>输入</dt><dd>{{ item.input }}</dd></div>
            <div><dt>输出</dt><dd>{{ item.output }}</dd></div>
          </dl>
          <div v-if="item.labels.length" class="ai-labels">
            <span v-for="key in item.labels" :key="key" class="ai-chip">
              <i :style="{ backgroundColor: lesionColor(key) }" />{{ key }} {{ lesionName(key) }}
            </span>
          </div>
          <p v-if="item.status === 'not_deployed'" class="ai-note">
            尚未部署到 CSU-EYES 算法服务器（{{ item.endpoint }}），部署后即可选择。
          </p>

          <div v-if="states[item.key] && states[item.key] !== 'idle'" class="ai-run" :class="`is-${states[item.key]}`">
            <div class="ai-run-state">
              <span class="ai-dot" aria-hidden="true" />
              {{ RUN_TEXT[states[item.key]] }}
              <span v-if="results[item.key]?.seconds" class="ai-secs">{{ results[item.key]!.seconds.toFixed(1) }} 秒</span>
            </div>
            <p v-if="errors[item.key]" class="ai-msg">{{ errors[item.key] }}</p>
            <template v-else-if="results[item.key]">
              <p class="ai-msg">{{ results[item.key]!.message }}</p>

              <div v-if="Object.keys(results[item.key]!.counts || {}).length" class="ai-labels">
                <span v-for="(n, key) in results[item.key]!.counts" :key="key" class="ai-chip">
                  <i :style="{ backgroundColor: lesionColor(String(key)) }" />{{ lesionName(String(key)) }} {{ n }}
                </span>
              </div>

              <div v-if="results[item.key]!.metrics" class="ai-metrics">
                <div><span>垂直杯盘比</span><strong>{{ formatCdr(results[item.key]!.metrics!.verticalCdr) }}</strong></div>
                <div><span>水平杯盘比</span><strong>{{ formatCdr(results[item.key]!.metrics!.horizontalCdr) }}</strong></div>
                <div v-if="results[item.key]!.metrics!.riskName">
                  <span>风险</span><strong>{{ results[item.key]!.metrics!.riskName }}</strong>
                </div>
              </div>

              <div v-if="results[item.key]!.classification" class="ai-probs">
                <div v-for="row in probabilityRows(results[item.key]!)" :key="row.label" class="ai-prob">
                  <span class="ai-prob-label">{{ row.label }}</span>
                  <span class="ai-prob-bar"><i :style="{ width: `${row.pct}%` }" /></span>
                  <span class="ai-prob-val">{{ row.pct }}%</span>
                </div>
              </div>

              <el-button
                v-if="results[item.key]!.overlayUrl"
                size="small"
                :type="activeOverlay === item.key ? 'primary' : 'default'"
                plain
                @click="showOverlay(results[item.key]!)"
              >
                {{ activeOverlay === item.key ? '已叠加到画布' : '叠加到画布' }}
              </el-button>
            </template>
          </div>
        </li>
      </ul>
    </div>

    <template #footer>
      <div class="ai-footer">
        <el-button :disabled="catalogLoading || running" @click="loadCatalog">刷新状态</el-button>
        <el-button
          type="primary"
          :loading="running"
          :disabled="!selected.length || !imageUrl || !caseId"
          @click="runSelected"
        >
          {{ running ? '运行中' : `运行所选（${selected.length}）` }}
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.ai-drawer-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ai-intro {
  margin: 0;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
.ai-loading {
  padding: 24px 0;
  text-align: center;
  color: var(--el-text-color-secondary);
}
.ai-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.ai-item {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--el-bg-color);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ai-item.disabled .ai-item-name,
.ai-item.disabled .ai-meta {
  color: var(--el-text-color-placeholder);
}
.ai-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.ai-item-name {
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.ai-item-tags {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.ai-meta {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.ai-meta div {
  display: flex;
  gap: 8px;
}
.ai-meta dt {
  flex-shrink: 0;
  width: 28px;
  color: var(--el-text-color-secondary);
}
.ai-meta dd {
  margin: 0;
}
.ai-labels {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.ai-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 1px 8px;
  border-radius: 10px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
}
.ai-chip i {
  width: 8px;
  height: 8px;
  border-radius: 2px;
}
.ai-note {
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.ai-run {
  border-top: 1px dashed var(--el-border-color-lighter);
  padding-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}
.ai-run-state {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--el-text-color-regular);
}
.ai-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--el-text-color-placeholder);
}
.is-running .ai-dot {
  background: var(--el-color-primary);
  animation: ai-pulse 1s ease-in-out infinite;
}
.is-done .ai-dot {
  background: var(--el-color-success);
}
.is-failed .ai-dot {
  background: var(--el-color-danger);
}
.is-failed .ai-msg {
  color: var(--el-color-danger);
}
.ai-secs {
  font-weight: 400;
  color: var(--el-text-color-secondary);
}
.ai-msg {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
}
.ai-metrics {
  display: flex;
  gap: 16px;
  font-size: 12px;
}
.ai-metrics div {
  display: flex;
  flex-direction: column;
}
.ai-metrics span {
  color: var(--el-text-color-secondary);
}
.ai-metrics strong {
  font-size: 18px;
  color: var(--el-text-color-primary);
}
.ai-probs {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ai-prob {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}
.ai-prob-label {
  width: 72px;
  flex-shrink: 0;
  color: var(--el-text-color-regular);
}
.ai-prob-bar {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--el-fill-color);
  overflow: hidden;
}
.ai-prob-bar i {
  display: block;
  height: 100%;
  background: var(--el-color-primary);
}
.ai-prob-val {
  width: 44px;
  text-align: right;
  color: var(--el-text-color-secondary);
}
.ai-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
@keyframes ai-pulse {
  50% {
    opacity: 0.3;
  }
}
@media (prefers-reduced-motion: reduce) {
  .is-running .ai-dot {
    animation: none;
  }
}
</style>

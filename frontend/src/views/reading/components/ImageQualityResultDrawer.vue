<script setup lang="ts">
import { computed } from 'vue'
import type { QualityCaseResult, QualityResultItem } from '@/api/reading'

const props = defineProps<{
  modelValue: boolean
  result: QualityCaseResult | null
  loading?: boolean
  errorText?: string
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', v: boolean): void
  (e: 'retry'): void
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

type TagType = 'success' | 'warning' | 'danger' | 'info'

const VERDICT_TAG: Record<string, TagType> = {
  pass: 'success',
  incomplete: 'warning',
  unchecked: 'info',
  ungradable: 'danger',
  empty: 'info',
}
const VERDICT_TITLE: Record<string, string> = {
  pass: '合格',
  incomplete: '需复核',
  unchecked: '未质控',
  ungradable: '不可判读',
  empty: '无原图',
}
const QUALITY_TAG: Record<string, TagType> = {
  good: 'success',
  usable: 'success',
  poor: 'danger',
  ungradable: 'danger',
  unknown: 'info',
}
const PROB_COLOR: Record<string, string> = {
  good: 'var(--el-color-success)',
  usable: 'var(--el-color-primary)',
  poor: 'var(--el-color-warning)',
  ungradable: 'var(--el-color-danger)',
}

const summary = computed(() => props.result?.summary)
const items = computed(() => props.result?.items || [])

const pct = (v: number) => `${Math.round((v || 0) * 100)}%`
const gradableText = (it: QualityResultItem) =>
  it.gradable === null ? '未评估' : it.gradable ? '可用于判读' : '不可用于判读'
</script>

<template>
  <el-drawer v-model="visible" title="图像质控结果" size="440px" direction="rtl" class="iq-drawer">
    <div v-loading="loading" class="iq-body">
      <el-alert v-if="errorText" :title="errorText" type="error" :closable="false" show-icon>
        <el-button size="small" link type="primary" @click="emit('retry')">重新读取</el-button>
      </el-alert>

      <template v-else-if="summary">
        <section class="iq-summary" :class="`is-${summary.verdict}`" aria-live="polite">
          <div class="iq-summary-head">
            <span class="iq-summary-label">病例结论</span>
            <el-tag :type="VERDICT_TAG[summary.verdict]" effect="dark" size="small">
              {{ VERDICT_TITLE[summary.verdict] || summary.verdict }}
            </el-tag>
          </div>
          <p class="iq-summary-text">{{ summary.verdictText }}</p>
          <dl class="iq-summary-meta">
            <div><dt>原图</dt><dd>{{ summary.total }} 张</dd></div>
            <div><dt>已评估</dt><dd>{{ summary.evaluated }} 张</dd></div>
            <div><dt>不可判读</dt><dd>{{ summary.ungradable }} 张</dd></div>
            <div v-if="summary.lastCheckedAt"><dt>评估时间</dt><dd>{{ summary.lastCheckedAt }}</dd></div>
          </dl>
        </section>

        <ul class="iq-list">
          <li v-for="it in items" :key="it.imageId" class="iq-item">
            <div class="iq-item-head">
              <img
                v-if="it.url"
                :src="it.url"
                :alt="`原图 ${it.index}（${it.eyeText}）`"
                class="iq-thumb"
                loading="lazy"
              />
              <div class="iq-item-title">
                <div class="iq-item-name">
                  原图 {{ it.index }} · {{ it.eyeText }}
                </div>
                <div class="iq-item-tags">
                  <el-tag :type="QUALITY_TAG[it.quality]" size="small">{{ it.qualityText }}</el-tag>
                  <span v-if="it.evaluated" class="iq-conf">置信度 {{ pct(it.confidence) }}</span>
                  <span class="iq-gradable" :class="{ bad: it.gradable === false }">
                    {{ gradableText(it) }}
                  </span>
                </div>
              </div>
            </div>

            <div v-if="it.probabilities.length" class="iq-probs" aria-label="各等级概率">
              <div v-for="p in it.probabilities" :key="p.level" class="iq-prob">
                <span class="iq-prob-label">{{ p.label }}</span>
                <div class="iq-prob-track" role="presentation">
                  <div
                    class="iq-prob-bar"
                    :style="{ width: pct(p.value), background: PROB_COLOR[p.level] }"
                  />
                </div>
                <span class="iq-prob-val">{{ pct(p.value) }}</span>
              </div>
            </div>

            <p class="iq-advice" :class="{ warn: it.gradable !== true }">{{ it.advice }}</p>
            <p v-if="it.modelName || it.checkedAt" class="iq-foot">
              <span v-if="it.modelName">模型 {{ it.modelName }}</span>
              <span v-if="it.checkedAt">{{ it.checkedAt }}</span>
            </p>
          </li>
        </ul>

        <p class="iq-note">
          现有算法只给出总等级和各等级概率。清晰度、曝光、遮挡、伪影等分项指标需接入专项算法，此处不显示。
        </p>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.iq-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-height: 120px;
}
.iq-summary {
  padding: 14px 16px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color);
  background: var(--el-fill-color-lighter);
}
.iq-summary.is-pass { border-color: var(--el-color-success-light-5); }
.iq-summary.is-incomplete { border-color: var(--el-color-warning-light-5); }
.iq-summary.is-ungradable { border-color: var(--el-color-danger-light-5); }
.iq-summary-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.iq-summary-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.iq-summary-text {
  margin: 8px 0 10px;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--el-text-color-primary);
}
.iq-summary-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 16px;
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.iq-summary-meta div { display: flex; gap: 4px; }
.iq-summary-meta dd { margin: 0; color: var(--el-text-color-regular); }

.iq-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.iq-item {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-bg-color);
}
.iq-item-head { display: flex; gap: 12px; align-items: center; }
.iq-thumb {
  width: 64px;
  height: 64px;
  flex-shrink: 0;
  object-fit: cover;
  border-radius: 6px;
  background: #000;
}
.iq-item-title { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.iq-item-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}
.iq-item-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.iq-gradable { color: var(--el-color-success); }
.iq-gradable.bad { color: var(--el-color-danger); }

.iq-probs { display: flex; flex-direction: column; gap: 6px; }
.iq-prob {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.iq-prob-label { width: 56px; flex-shrink: 0; }
.iq-prob-track {
  flex: 1;
  height: 6px;
  border-radius: 3px;
  background: var(--el-fill-color);
  overflow: hidden;
}
.iq-prob-bar { height: 100%; border-radius: 3px; }
.iq-prob-val { width: 40px; text-align: right; font-variant-numeric: tabular-nums; }

.iq-advice {
  margin: 0;
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-light);
}
.iq-advice.warn {
  color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}
.iq-foot {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin: 0;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.iq-note {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
</style>

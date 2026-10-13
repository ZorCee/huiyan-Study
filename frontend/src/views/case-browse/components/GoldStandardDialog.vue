<script setup lang="ts">
/**
 * 完善 / 修订金标准
 * 保存草稿 → 仍未发布，学员不可见
 * 发布并加入实训 → is_published + is_train_case
 */
import { computed, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { EditPen, WarningFilled } from '@element-plus/icons-vue'
import { CaseBrowseApi } from '@/api'
import { DISEASES, SOURCE_META, optionLabel, type CaseFinding } from '@/utils/case-findings'
import {
  TEACHING_OUTLINE,
  emptyTeachingSections,
  parseTeachingPoints,
  serializeTeachingPoints
} from '@/utils/teaching-outline'

type Detail = CaseBrowseApi.CaseBrowseDetail

const LESION_OPTIONS = [
  { label: '微动脉瘤 MA', value: 'MA' },
  { label: '出血 HE', value: 'HE' },
  { label: '硬性渗出 EX', value: 'EX' },
  { label: '软性渗出 SE', value: 'SE' }
]

const props = defineProps<{
  visible: boolean
  data: Detail | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
  (e: 'saved', detail: Detail, published: boolean): void
}>()

const dialogVisible = computed({
  get: () => props.visible,
  set: (v) => emit('update:visible', v)
})

const form = reactive({
  findings: {} as Record<string, string>,
  goldDiagnosis: '',
  sections: emptyTeachingSections(),
  passScore: 60,
  lesionTypes: [] as string[]
})
const legacyPoints = ref('')

const saving = ref(false)
const publishing = ref(false)

/** 打开弹窗时的结论，用来判断哪些病种被教师改过、显示来源和 AI 建议 */
const original = ref<Record<string, CaseFinding>>({})

const hydrate = (d: Detail | null) => {
  const map: Record<string, CaseFinding> = {}
  for (const f of d?.findings || []) map[f.disease] = f
  const legacyDr = d?.goldDrGrade ?? (d?.drLevel != null ? String(d.drLevel) : '')
  if (!map.DR && legacyDr) {
    map.DR = {
      disease: 'DR', diseaseLabel: '', value: legacyDr,
      valueLabel: optionLabel('DR', legacyDr), source: 'DATASET'
    }
  }
  original.value = map
  form.findings = Object.fromEntries(DISEASES.map((x) => [x.key, map[x.key]?.value || '']))
  form.goldDiagnosis = d?.goldDiagnosis || ''
  const parsed = parseTeachingPoints(d?.teachingPoints || '')
  form.sections = { ...emptyTeachingSections(), ...parsed.sections }
  legacyPoints.value = parsed.legacy
  form.passScore = d?.passScore ?? 60
  form.lesionTypes = (d?.goldLesions || [])
    .map((x) => String(x?.type || x?.label || '').trim())
    .filter(Boolean)
}

watch(
  () => props.visible,
  (open) => {
    if (open) hydrate(props.data)
  }
)

const buildLesions = () => {
  const prev = new Map(
    (props.data?.goldLesions || []).map((x) => [String(x?.type || ''), x])
  )
  return form.lesionTypes.map((t) => prev.get(t) || { type: t })
}

const isChanged = (disease: string) =>
  (form.findings[disease] || '') !== (original.value[disease]?.value || '')

const aiSuggestion = (disease: string) => original.value[disease]?.aiValue || ''

/** 当前值与 AI 建议不一致；仍是 AI 来源且未改动时不算冲突 */
const conflictOf = (disease: string) => {
  const ai = aiSuggestion(disease)
  const value = form.findings[disease] || ''
  if (!ai || !value || ai === value) return false
  return isChanged(disease) || original.value[disease]?.source !== 'AI'
}

const sourceTag = (disease: string) => {
  if (!form.findings[disease]) return null
  if (isChanged(disease)) return { text: '人工（未保存）', type: 'success' as const }
  const src = original.value[disease]?.source
  return src ? SOURCE_META[src] : null
}

const conflictCount = computed(() => DISEASES.filter((x) => conflictOf(x.key)).length)
const titleConflicts = computed(() =>
  (props.data?.findingConflicts || []).filter((c) => c.startsWith('标题') && !isChanged('DR'))
)

/** 只提交改过的病种，未改动的 AI 来源保持「待复核」 */
const changedFindings = () =>
  DISEASES.filter((x) => isChanged(x.key)).map((x) => ({
    disease: x.key,
    value: form.findings[x.key] || ''
  }))

const payload = (): CaseBrowseApi.GoldStandardUpdate => ({
  findings: changedFindings(),
  goldDiagnosis: form.goldDiagnosis.trim(),
  teachingPoints: serializeTeachingPoints(form.sections) || legacyPoints.value.trim(),
  passScore: form.passScore,
  goldLesions: buildLesions()
})

const submit = async (publish: boolean) => {
  if (!props.data?.id) return
  if (publish && !form.goldDiagnosis.trim()) {
    return
  }
  if (publish && (conflictCount.value || titleConflicts.value.length)) {
    try {
      await ElMessageBox.confirm(
        '金标准与 AI 建议或标题仍不一致。发布后以当前金标准为准，来源记为人工，学员按此评分。确定发布吗？',
        '存在冲突',
        { type: 'warning', confirmButtonText: '确认发布', cancelButtonText: '再看看' }
      )
    } catch {
      return
    }
  }
  const flag = publish ? publishing : saving
  flag.value = true
  try {
    const detail = await CaseBrowseApi.updateGoldStandard(props.data.id, {
      ...payload(),
      publish
    })
    emit('saved', detail, publish)
    dialogVisible.value = false
  } catch {
    /* 拦截器已弹错 */
  } finally {
    flag.value = false
  }
}

const isDraft = computed(() => !props.data?.isPublished)
const title = computed(() =>
  isDraft.value ? '完善金标准' : '修订金标准'
)
</script>

<template>
  <el-dialog
    v-model="dialogVisible"
    :title="title"
    width="760"
    :close-on-click-modal="false"
    destroy-on-close
  >
    <div v-if="data" class="gold-head">
      <span class="case-no">{{ data.caseNo }}</span>
      <span class="case-title">{{ data.title || '—' }}</span>
      <el-tag v-if="isDraft" type="warning" size="small" effect="plain">草稿 · 未发布</el-tag>
      <el-tag v-else-if="data.isTrainCase" type="success" size="small" effect="dark">已加入实训</el-tag>
      <el-tag v-else type="success" size="small" effect="plain">已发布</el-tag>
    </div>

    <el-alert
      v-if="data?.qualitySummary?.lowQuality"
      :type="data.qualitySummary.level === 'ungradable' ? 'error' : 'warning'"
      :closable="false"
      show-icon
      :title="`图像质控：${data.qualitySummary.levelText}（${data.qualitySummary.eyes.map((e) => `${e.eyeText} ${e.qualityText}`).join('，')}）`"
      :description="
        data.qualitySummary.override
          ? `已人工放行：${data.qualitySummary.override.reason}（${data.qualitySummary.override.at}）。默认不进入练习与考试抽题。`
          : '该病例默认不进入练习与考试抽题，请复核图像后再决定是否发布。'
      "
      class="title-conflict"
    />

    <el-alert
      v-for="(c, i) in titleConflicts"
      :key="i"
      type="warning"
      :closable="false"
      show-icon
      :title="c"
      class="title-conflict"
    />

    <el-form label-width="132px" class="gold-form">
      <el-form-item
        v-for="d in DISEASES"
        :key="d.key"
        :label="d.key === 'DR' ? '金标准 DR 分级' : `金标准 ${d.label}`"
      >
        <div class="finding-block" :class="{ 'is-conflict': conflictOf(d.key) }">
          <div class="finding-main">
            <el-select
              v-if="d.key === 'DR'"
              v-model="form.findings[d.key]"
              class="finding-select"
            >
              <el-option label="不适用（非 DR 病种）" value="" />
              <el-option v-for="o in d.options" :key="o.value" :label="o.label" :value="o.value" />
            </el-select>
            <el-radio-group v-else v-model="form.findings[d.key]">
              <el-radio-button value="">不填</el-radio-button>
              <el-radio-button v-for="o in d.options" :key="o.value" :value="o.value">
                {{ o.label }}
              </el-radio-button>
            </el-radio-group>
            <el-tag
              v-if="sourceTag(d.key)"
              :type="sourceTag(d.key)!.type"
              size="small"
              effect="plain"
            >
              {{ sourceTag(d.key)!.text }}
            </el-tag>
          </div>
          <div v-if="aiSuggestion(d.key)" class="finding-ai">
            <el-icon v-if="conflictOf(d.key)"><WarningFilled /></el-icon>
            <span>
              AI 建议：{{ optionLabel(d.key, aiSuggestion(d.key)) || aiSuggestion(d.key) }}
              <template v-if="conflictOf(d.key)">，与当前金标准不一致</template>
            </span>
            <el-button
              v-if="form.findings[d.key] !== aiSuggestion(d.key)"
              link
              type="primary"
              size="small"
              @click="form.findings[d.key] = aiSuggestion(d.key)"
            >
              选用 AI 值
            </el-button>
            <el-button
              v-if="isChanged(d.key)"
              link
              size="small"
              @click="form.findings[d.key] = original[d.key]?.value || ''"
            >
              还原
            </el-button>
          </div>
        </div>
      </el-form-item>
      <el-form-item label="金标准诊断" required>
        <el-input
          v-model="form.goldDiagnosis"
          type="textarea"
          :rows="3"
          maxlength="500"
          show-word-limit
          placeholder="学员提交后对照的诊断结论，例如：中度 NPDR，可见微动脉瘤与点状出血"
        />
      </el-form-item>
      <el-form-item label="教学要点">
        <p class="outline-tip">按固定提纲填写。没写的项不会保存，学员端也只看到已填的项。</p>
        <p v-if="legacyPoints" class="legacy">
          这条还是自由文本。填进下面各项并保存后，就按提纲存放。原文：{{ legacyPoints }}
        </p>
      </el-form-item>
      <el-form-item v-for="item in TEACHING_OUTLINE" :key="item.key" :label="item.label">
        <el-input
          v-model="form.sections[item.key]"
          type="textarea"
          :rows="2"
          maxlength="400"
          show-word-limit
          :placeholder="item.placeholder"
        />
      </el-form-item>
      <el-form-item label="典型病变">
        <el-checkbox-group v-model="form.lesionTypes">
          <el-checkbox v-for="opt in LESION_OPTIONS" :key="opt.value" :label="opt.value">
            {{ opt.label }}
          </el-checkbox>
        </el-checkbox-group>
      </el-form-item>
      <el-form-item label="及格分">
        <el-input-number v-model="form.passScore" :min="0" :max="100" :step="5" />
        <span class="muted">百分制，学员自主练习按此线判定是否通过</span>
      </el-form-item>
    </el-form>

    <el-alert
      v-if="isDraft"
      type="info"
      :closable="false"
      show-icon
      title="保存草稿后学员仍不可见；「发布并加入实训」后，学员抽题与阅片才能看到该病例。"
    />

    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button :loading="saving" :disabled="publishing" @click="submit(false)">
        {{ isDraft ? '保存草稿' : '保存修订' }}
      </el-button>
      <el-button
        type="primary"
        :icon="EditPen"
        :loading="publishing"
        :disabled="saving || !form.goldDiagnosis.trim()"
        @click="submit(true)"
      >
        发布并加入实训
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.gold-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.case-no {
  font-family: 'Consolas', 'Monaco', monospace;
  color: #1677ff;
  font-weight: 700;
}
.case-title {
  font-weight: 600;
  color: var(--hy-c-text, #1d2129);
}
.gold-form {
  margin-bottom: 12px;
}
.title-conflict {
  margin-bottom: 14px;
}
.finding-block {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid transparent;
}
.finding-block.is-conflict {
  border-color: var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
}
.finding-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.finding-select {
  flex: 1;
  min-width: 220px;
}
.finding-ai {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
  line-height: 1.5;
  color: var(--hy-c-text-2, #4e5969);
}
.finding-block.is-conflict .finding-ai {
  color: var(--el-color-warning-dark-2);
}
.muted {
  margin-left: 10px;
  color: var(--hy-c-text-3, #86909c);
  font-size: 12px;
}
.outline-tip,
.legacy {
  margin: 0;
  line-height: 1.6;
  font-size: 13px;
  color: var(--hy-c-text-2, #4e5969);
}
.legacy {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--hy-c-warning-soft, #fff7e8);
  color: var(--hy-c-text, #1d2129);
}
</style>

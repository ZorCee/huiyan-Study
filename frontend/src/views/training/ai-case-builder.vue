<script setup lang="ts">
/**
 * AI 智能建案（教师 / 管理员）
 * 上传左右眼底图 → CSU-EYES 算法自动 DR 分级 → 生成实训病例草稿
 * 金标准预填为 AI 结果，教师在管理后台复核修订后发布给学生。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { MagicStick, Plus, View, WarningFilled } from '@element-plus/icons-vue'
import { CaseBrowseApi, TrainingApi } from '@/api'
import { DISEASES, SOURCE_META, hasConflict, type CaseFinding } from '@/utils/case-findings'

const DR_CHOICES = DISEASES.find((d) => d.key === 'DR')!.options
const GLAUCOMA_CHOICES = DISEASES.find((d) => d.key === 'GLAUCOMA')!.options

const router = useRouter()
defineProps<{ embedded?: boolean }>()

/* ========== 上传 ========== */
interface EyeSlot {
  file: File | null
  preview: string
}
const leftEye = ref<EyeSlot>({ file: null, preview: '' })
const rightEye = ref<EyeSlot>({ file: null, preview: '' })

const ACCEPT = ['image/jpeg', 'image/png']
const pick = (side: 'left' | 'right') => {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.jpg,.jpeg,.png'
  input.onchange = () => {
    const f = input.files?.[0]
    if (!f) return
    if (!ACCEPT.includes(f.type)) {
      ElMessage.warning('算法服务仅支持 JPG / PNG 眼底图')
      return
    }
    if (f.size > 20 * 1024 * 1024) {
      ElMessage.warning('图片不能超过 20MB')
      return
    }
    const slot = side === 'left' ? leftEye : rightEye
    if (slot.value.preview) URL.revokeObjectURL(slot.value.preview)
    slot.value = { file: f, preview: URL.createObjectURL(f) }
    consent.value = emptyConsent()
  }
  input.click()
}

/* ========== 建案表单 ========== */
const emptyForm = () => ({
  title: '',
  difficulty: 'EASY' as 'EASY' | 'MEDIUM' | 'HARD',
  manualDr: '',
  manualGlaucoma: '',
  screenGlaucoma: false
})
const form = ref(emptyForm())

const canSubmit = computed(() => !!leftEye.value.file && !!rightEye.value.file)

/* ========== 提交 ========== */
const submitting = ref(false)
const draft = ref<TrainingApi.AiCaseDraft | null>(null)

/* 质控确认：只对当前这组图片有效，换图即清空 */
const emptyConsent = () => ({ confirmLowQuality: false, confirmLaterality: false, overrideReason: '' })
const consent = ref(emptyConsent())
const gate = ref<TrainingApi.CaseQualityGate | null>(null)
const gateVisible = ref(false)
const overrideDraft = ref('')

const GATE_META: Record<TrainingApi.CaseQualityGate['kind'], { title: string; type: 'warning' | 'error' }> = {
  LATERALITY_CONFLICT: { title: '请确认眼别', type: 'warning' },
  QUALITY_POOR: { title: '图像质量较差', type: 'warning' },
  QUALITY_UNGRADABLE: { title: '图像不可判读，已阻止建案', type: 'error' }
}
const QUALITY_TAG: Record<string, 'success' | 'warning' | 'danger' | 'info'> = {
  good: 'success', usable: 'success', poor: 'warning', ungradable: 'danger', unknown: 'info'
}

const handleCreate = async () => {
  if (!leftEye.value.file || !rightEye.value.file) {
    ElMessage.warning('请先上传左、右眼底图各一张')
    return
  }
  submitting.value = true
  try {
    draft.value = await TrainingApi.createAiCase(
      leftEye.value.file,
      rightEye.value.file,
      { ...form.value, ...consent.value }
    )
    gateVisible.value = false
    ElMessage.success(`建案成功：${draft.value.caseId}（草稿，待复核发布）`)
  } catch (err: any) {
    const blocked = TrainingApi.readQualityGate(err)
    if (blocked) {
      gate.value = blocked
      overrideDraft.value = consent.value.overrideReason
      gateVisible.value = true
    } else {
      ElMessage.error(err?.message || '建案失败，请稍后重试')
    }
  } finally {
    submitting.value = false
  }
}

const continueAfterGate = () => {
  const kind = gate.value?.kind
  if (kind === 'LATERALITY_CONFLICT') consent.value.confirmLaterality = true
  else if (kind === 'QUALITY_POOR') consent.value.confirmLowQuality = true
  else if (kind === 'QUALITY_UNGRADABLE') {
    const reason = overrideDraft.value.trim()
    if (!reason) {
      ElMessage.warning('人工放行必须填写理由')
      return
    }
    consent.value.overrideReason = reason
  }
  handleCreate()
}

const reuploadFromGate = () => {
  gateVisible.value = false
  consent.value = emptyConsent()
}

const goFinishGold = () => {
  if (!draft.value) return
  const query: Record<string, string> = { tab: 'browse' }
  if (draft.value.id) query.goldCaseId = String(draft.value.id)
  if (draft.value.caseId) query.keyword = draft.value.caseId
  router.push({ path: '/training/cases', query })
}

const resetAll = () => {
  if (leftEye.value.preview) URL.revokeObjectURL(leftEye.value.preview)
  if (rightEye.value.preview) URL.revokeObjectURL(rightEye.value.preview)
  leftEye.value = { file: null, preview: '' }
  rightEye.value = { file: null, preview: '' }
  form.value = emptyForm()
  consent.value = emptyConsent()
  gate.value = null
  draft.value = null
}

/* ========== 冲突：点一下选用人工值或 AI 值 ========== */
const resolving = ref('')
const pickValue = async (f: CaseFinding, value: string) => {
  if (!draft.value?.id) return
  resolving.value = `${f.disease}:${value}`
  try {
    const detail = await CaseBrowseApi.updateGoldStandard(draft.value.id, {
      findings: [{ disease: f.disease, value }],
      publish: false
    })
    draft.value = {
      ...draft.value,
      findings: detail.findings || [],
      conflicts: detail.findingConflicts || []
    }
    ElMessage.success('已更新金标准，来源记为人工')
  } catch {
    /* 拦截器已弹错 */
  } finally {
    resolving.value = ''
  }
}

const GRADE_TAG: Record<number, 'success' | 'warning' | 'danger'> = {
  0: 'success', 1: 'success', 2: 'warning', 3: 'danger', 4: 'danger'
}
</script>

<template>
  <div class="ai-builder-page" :class="{ 'is-embedded': embedded }">
    <header class="page-head">
      <div>
        <h2 class="title">
          <el-icon><MagicStick /></el-icon>
          AI 智能建案
        </h2>
        <p class="subtitle">
          上传左右眼底图，CSU-EYES 算法服务自动完成 DR 分级与 GradCAM 热力图，一键生成实训病例草稿；
          金标准预填为 AI 结果，复核修订后即可发布给学生练习。
        </p>
      </div>
    </header>

    <!-- 结果态 -->
    <el-card v-if="draft" class="result-card" shadow="never">
      <el-result icon="success" :title="`建案成功：${draft.caseId}`" :sub-title="draft.title">
        <template #extra>
          <div class="result-grades">
            <template v-if="draft.aiReturned !== false">
              <el-tag :type="GRADE_TAG[draft.ai.overallGrade] || 'info'" size="large" effect="dark">
                AI 综合 DR {{ draft.ai.overallGrade }} 级
              </el-tag>
              <el-tag type="info" effect="plain">OS {{ draft.ai.left.grade }} 级</el-tag>
              <el-tag type="info" effect="plain">OD {{ draft.ai.right.grade }} 级</el-tag>
            </template>
            <el-tag v-else type="danger" size="large" effect="plain">AI 未返回 DR 分级</el-tag>
            <el-tag type="warning" effect="plain">草稿 · 未发布</el-tag>
          </div>

          <div v-if="draft.quality?.length" class="quality-row">
            <span class="quality-label">图像质控</span>
            <el-tag
              v-for="q in draft.quality"
              :key="q.eye"
              :type="QUALITY_TAG[q.quality] || 'info'"
              size="small"
              effect="plain"
            >
              {{ q.eyeText }} · {{ q.qualityText }}
            </el-tag>
          </div>
          <el-alert
            v-for="(w, i) in [...(draft.qualityWarnings || []), ...(draft.laterality || [])]"
            :key="`q${i}`"
            type="warning"
            :closable="false"
            show-icon
            :title="w"
            class="title-conflict"
          />
          <el-alert
            v-if="draft.qualityOverride"
            type="error"
            :closable="false"
            show-icon
            :title="`不可判读图像已人工放行：${draft.qualityOverride.reason}`"
            description="该病例默认不进入练习与考试抽题。"
            class="title-conflict"
          />

          <ul v-if="draft.findings?.length" class="finding-list">
            <li
              v-for="f in draft.findings"
              :key="f.disease"
              class="finding-row"
              :class="{ 'is-conflict': hasConflict(f) }"
            >
              <span class="finding-name">{{ f.diseaseLabel }}</span>
              <span class="finding-value">{{ f.valueLabel || f.value }}</span>
              <el-tag :type="SOURCE_META[f.source]?.type" size="small" effect="plain">
                {{ SOURCE_META[f.source]?.text || f.source }}
              </el-tag>
              <template v-if="hasConflict(f)">
                <span class="finding-ai">
                  <el-icon><WarningFilled /></el-icon>
                  AI 建议 {{ f.aiValueLabel || f.aiValue }}
                </span>
                <el-button
                  size="small"
                  :loading="resolving === `${f.disease}:${f.value}`"
                  @click="pickValue(f, f.value)"
                >
                  保留{{ SOURCE_META[f.source]?.text }}值
                </el-button>
                <el-button
                  size="small"
                  type="warning"
                  plain
                  :loading="resolving === `${f.disease}:${f.aiValue}`"
                  @click="pickValue(f, f.aiValue || '')"
                >
                  选用 AI 值
                </el-button>
              </template>
            </li>
          </ul>

          <el-alert
            v-for="(c, i) in (draft.conflicts || []).filter((c) => c.startsWith('标题'))"
            :key="i"
            type="warning"
            :closable="false"
            show-icon
            :title="c"
            class="title-conflict"
          />
          <div class="result-heat">
            <el-image
              v-for="(u, i) in [draft.ai.left.heatmapUrl, draft.ai.right.heatmapUrl].filter(Boolean)"
              :key="i"
              :src="u"
              fit="cover"
              class="heat-thumb"
              :preview-src-list="[draft.ai.left.heatmapUrl, draft.ai.right.heatmapUrl].filter(Boolean)"
              preview-teleported
            />
          </div>
          <div class="result-actions">
            <el-button type="primary" :icon="View" @click="goFinishGold">
              去完善金标准
            </el-button>
            <el-button :icon="Plus" @click="resetAll">继续建案</el-button>
          </div>
        </template>
      </el-result>
    </el-card>

    <!-- 表单态 -->
    <el-card v-else class="form-card" shadow="never">
      <div class="upload-grid">
        <div
          v-for="side in (['left', 'right'] as const)"
          :key="side"
          class="upload-cell"
          @click="pick(side)"
        >
          <template v-if="(side === 'left' ? leftEye : rightEye).preview">
            <img :src="(side === 'left' ? leftEye : rightEye).preview" class="upload-preview" />
            <div class="upload-mask">点击更换</div>
          </template>
          <template v-else>
            <el-icon class="upload-icon"><Plus /></el-icon>
            <div class="upload-text">{{ side === 'left' ? '左眼 OS' : '右眼 OD' }} 眼底图</div>
            <div class="upload-hint">JPG / PNG，≤ 20MB</div>
          </template>
        </div>
      </div>

      <el-form label-width="88px" class="meta-form">
        <el-form-item label="病例标题">
          <el-input
            v-model="form.title"
            placeholder="只用来描述病例，分级请在下方「人工预判」里选"
            maxlength="60"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="人工预判 DR">
          <el-select v-model="form.manualDr" style="width: 100%">
            <el-option label="不填，用 AI 结果（待复核）" value="" />
            <el-option v-for="o in DR_CHOICES" :key="o.value" :label="o.label" :value="o.value" />
          </el-select>
          <p class="field-hint">填了就以人工为准，AI 结果只作建议；不一致会提示冲突。</p>
        </el-form-item>
        <el-form-item label="青光眼">
          <div class="glaucoma-row">
            <el-radio-group v-model="form.manualGlaucoma">
              <el-radio-button value="">不填</el-radio-button>
              <el-radio-button v-for="o in GLAUCOMA_CHOICES" :key="o.value" :value="o.value">
                {{ o.label }}
              </el-radio-button>
            </el-radio-group>
            <el-checkbox v-model="form.screenGlaucoma">同时 AI 筛查青光眼</el-checkbox>
          </div>
          <p class="field-hint">勾选筛查会多调用一次算法服务，两眼都测，取风险更高的结果。</p>
        </el-form-item>
        <el-form-item label="难度">
          <el-radio-group v-model="form.difficulty">
            <el-radio-button value="EASY">入门</el-radio-button>
            <el-radio-button value="MEDIUM">中级</el-radio-button>
            <el-radio-button value="HARD">高级</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>

      <div class="form-actions">
        <el-button
          type="primary"
          size="large"
          :icon="MagicStick"
          :disabled="!canSubmit"
          :loading="submitting"
          @click="handleCreate"
        >
          {{ submitting ? 'AI 推理中（约 5~30 秒）…' : '开始 AI 建案' }}
        </el-button>
      </div>

      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="建案后病例为「未发布」草稿，学生不可见；请到病例库该行点「完善金标准」，保存草稿或发布并加入实训。"
        style="margin-top: 16px"
      />
    </el-card>

    <el-dialog
      v-model="gateVisible"
      :title="gate ? GATE_META[gate.kind].title : ''"
      width="520px"
      :close-on-click-modal="false"
      append-to-body
    >
      <template v-if="gate">
        <el-alert :type="GATE_META[gate.kind].type" :closable="false" show-icon :title="gate.message" />
        <ul class="gate-reasons">
          <li v-for="(r, i) in gate.reasons" :key="i">{{ r }}</li>
        </ul>
        <div v-if="gate.quality.length" class="quality-row">
          <span class="quality-label">每眼质控</span>
          <el-tag
            v-for="q in gate.quality"
            :key="q.eye"
            :type="QUALITY_TAG[q.quality] || 'info'"
            size="small"
            effect="plain"
          >
            {{ q.eyeText }} · {{ q.qualityText }}{{ q.source === 'PRECHECK' ? '（本地预检）' : '' }}
          </el-tag>
        </div>
        <template v-if="gate.kind === 'QUALITY_UNGRADABLE'">
          <p class="field-hint">
            建议重新上传清晰的眼底图。确需使用这组图片时，请填写放行理由；理由和操作人会记录在病例上，该病例默认不进入练习与考试抽题。
          </p>
          <el-input
            v-model="overrideDraft"
            type="textarea"
            :rows="3"
            maxlength="255"
            show-word-limit
            placeholder="例如：教学用图像质量较差的示例，用于讲解拍摄失败的情形"
          />
        </template>
        <p v-else-if="gate.kind === 'QUALITY_POOR'" class="field-hint">
          继续建案后病例会标记为图像质量较差，默认不进入练习与考试抽题。
        </p>
      </template>
      <template #footer>
        <el-button @click="reuploadFromGate">重新上传</el-button>
        <el-button
          v-if="gate"
          :type="gate.kind === 'QUALITY_UNGRADABLE' ? 'danger' : 'primary'"
          :loading="submitting"
          :disabled="gate.kind === 'QUALITY_UNGRADABLE' && !overrideDraft.trim()"
          @click="continueAfterGate"
        >
          {{
            gate.kind === 'LATERALITY_CONFLICT'
              ? '眼别无误，继续'
              : gate.kind === 'QUALITY_POOR'
                ? '已知晓，仍继续建案'
                : '人工放行并建案'
          }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.quality-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 12px;
}
.quality-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.gate-reasons {
  margin: 12px 0;
  padding-left: 20px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--el-text-color-regular);
}
.ai-builder-page {
  padding: 24px;
  max-width: 860px;
  margin: 0 auto;
}
.ai-builder-page.is-embedded {
  max-width: 920px;
  padding: 8px 8px 28px;
}
.page-head .title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 6px;
  font-size: 20px;
  color: var(--hy-c-text, #1d2129);
}
.page-head .subtitle {
  margin: 0 0 18px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--hy-c-text-2, #4e5969);
}

.form-card,
.result-card {
  background: var(--ap-glass, rgba(24, 26, 32, 0.7));
  border: 1px solid var(--ap-hairline, #2a2a2a);
}

.upload-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 18px;
}
.upload-cell {
  position: relative;
  height: 220px;
  border: 1.5px dashed var(--el-border-color);
  border-radius: 10px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  overflow: hidden;
  transition: border-color 0.2s;
}
.upload-cell:hover {
  border-color: var(--el-color-primary);
}
.upload-icon {
  font-size: 30px;
  color: var(--el-text-color-secondary);
}
.upload-text {
  font-size: 14px;
  font-weight: 600;
}
.upload-hint {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.upload-preview {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.upload-mask {
  position: absolute;
  inset: auto 0 0;
  padding: 6px 0;
  text-align: center;
  font-size: 12px;
  color: #fff;
  background: rgba(0, 0, 0, 0.55);
}

.meta-form {
  max-width: 560px;
}
.field-hint {
  margin: 4px 0 0;
  width: 100%;
  font-size: 12px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
}
.glaucoma-row {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}
.finding-list {
  list-style: none;
  margin: 0 auto 14px;
  padding: 0;
  max-width: 560px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.finding-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding: 8px 12px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
  text-align: left;
}
.finding-row.is-conflict {
  border-color: var(--el-color-warning-light-5);
  background: var(--el-color-warning-light-9);
}
.finding-name {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
.finding-value {
  font-weight: 600;
}
.finding-ai {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--el-color-warning-dark-2);
}
.title-conflict {
  max-width: 560px;
  margin: 0 auto 14px;
  text-align: left;
}
.form-actions {
  display: flex;
  justify-content: center;
  margin-top: 6px;
}

.result-grades {
  display: flex;
  justify-content: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.result-heat {
  display: flex;
  justify-content: center;
  gap: 10px;
  margin-bottom: 16px;
}
.heat-thumb {
  width: 160px;
  height: 120px;
  border-radius: 8px;
  overflow: hidden;
}
.result-actions {
  display: flex;
  justify-content: center;
  gap: 10px;
}
</style>

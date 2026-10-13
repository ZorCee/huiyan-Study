<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getGuidelineTemplates,
  generateByTemplate,
  createQuestion,
  type GuidelineTemplate,
  type QuestionCreatePayload
} from '@/api/question'

const props = defineProps<{
  modelValue: boolean
  caseId: number
  imageUrl: string
  currentAnnotations?: any[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'created'): void
}>()

const activeTab = ref<'image' | 'template' | 'custom_blank'>('image')
const loading = ref(false)
const templates = ref<GuidelineTemplate[]>([])
const selectedTemplateCode = ref<string>('')

// 逐图题表单
const imageForm = ref({
  stem: '图中高亮标注区域呈现的眼底特征性改变最符合下列哪种病变？',
  optionA: '微动脉瘤 (Microaneurysms)',
  optionB: '硬性渗出 (Hard Exudates)',
  optionC: '棉絮斑 / 软性渗出 (Cotton Wool Spots)',
  optionD: '视网膜内微血管异常 (IRMA)',
  answer: 'A',
  difficulty: 'MEDIUM',
  explanation: '高亮区域可见边界清楚的针尖样深红色小圆点，分布于后极部毛细血管网，为糖尿病视网膜病变最早期的微动脉瘤改变。',
  selectedAnnotationId: '',
  roiBox: null as any
})

// 自定义挖空题表单
const blankForm = ref({
  guideline: '我国糖尿病视网膜病变临床诊疗指南(2022年)',
  section: '第二部分·临床分期与分级标准',
  stem: '重度非增殖期糖尿病视网膜病变（NPDR）符合“4-2-1”原则，其中“4”指 {{blank_1}} 个象限均有严重视网膜内出血；“2”指 {{blank_2}} 个象限存在明显的静脉串珠；“1”指 {{blank_3}} 个象限出现显著的视网膜内微血管异常（IRMA）。',
  blank1Label: '出血象限数',
  blank1Answer: '4',
  blank1Alts: '4, 4个, 四, 四个',
  blank2Label: '静脉串珠象限数',
  blank2Answer: '2',
  blank2Alts: '2, 2个, 二, 两个',
  blank3Label: 'IRMA象限数',
  blank3Answer: '1',
  blank3Alts: '1, 1个, 一, 一个',
  difficulty: 'MEDIUM',
  explanation: '4-2-1 原则是国际与我国临床指南定义重度 NPDR 的核心标准，满足任一条即可诊断为重度 NPDR。'
})

const currentSelectedTemplate = computed(() =>
  templates.value.find((t) => t.code === selectedTemplateCode.value)
)

const loadTemplates = async () => {
  try {
    const res = await getGuidelineTemplates()
    templates.value = res.data || []
    if (templates.value.length && !selectedTemplateCode.value) {
      selectedTemplateCode.value = templates.value[0].code
    }
  } catch (err: any) {
    ElMessage.error('加载临床指南考点模板失败：' + (err.message || '网络异常'))
  }
}

watch(
  () => props.modelValue,
  (val) => {
    if (val) {
      loadTemplates()
      // 如果当前图上有标注，默认选中第一个
      if (props.currentAnnotations && props.currentAnnotations.length > 0) {
        const first = props.currentAnnotations[0]
        imageForm.value.selectedAnnotationId = first.id || ''
        imageForm.value.roiBox = first.points ? calcBoundingBox(first.points) : null
      }
    }
  }
)

const onAnnotationSelected = (annId: string) => {
  const ann = props.currentAnnotations?.find((a) => a.id === annId)
  if (ann && ann.points) {
    imageForm.value.roiBox = calcBoundingBox(ann.points)
    const label = ann.label || '病灶'
    imageForm.value.stem = `图中高亮标注区域呈现的 ${label} 特征性改变最符合下列哪种病变？`
  }
}

const calcBoundingBox = (points: Array<{ x: number; y: number }>) => {
  if (!points || !points.length) return null
  const xs = points.map((p) => p.x)
  const ys = points.map((p) => p.y)
  return [
    Math.round(Math.min(...xs)),
    Math.round(Math.min(...ys)),
    Math.round(Math.max(...xs)),
    Math.round(Math.max(...ys))
  ]
}

// 提交基于指南模板出题
const submitGenerateByTemplate = async () => {
  if (!selectedTemplateCode.value) return
  loading.value = true
  try {
    await generateByTemplate({
      templateCode: selectedTemplateCode.value,
      caseId: props.caseId || null
    })
    ElMessage.success('基于临床指南考点出题成功！已录入题库')
    emit('created')
    emit('update:modelValue', false)
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '出题失败')
  } finally {
    loading.value = false
  }
}

// 提交逐图题
const submitImageQuestion = async () => {
  if (!imageForm.value.stem.trim()) {
    ElMessage.warning('请输入题干内容')
    return
  }
  loading.value = true
  try {
    const options = [
      `A. ${imageForm.value.optionA}`,
      `B. ${imageForm.value.optionB}`,
      `C. ${imageForm.value.optionC}`,
      `D. ${imageForm.value.optionD}`
    ]
    const fullAnswer = options.find((o) => o.startsWith(imageForm.value.answer)) || options[0]

    const payload: QuestionCreatePayload = {
      questionType: 'IMAGE_LEVEL',
      caseId: props.caseId || null,
      imageUrl: props.imageUrl || null,
      stem: imageForm.value.stem,
      options,
      answer: fullAnswer,
      acceptAlternatives: [imageForm.value.answer, fullAnswer],
      roiBox: imageForm.value.roiBox,
      relatedAnnotationId: imageForm.value.selectedAnnotationId || null,
      sourceGuideline: '我国糖尿病视网膜病变临床诊疗指南(2022年)',
      sourceSection: '眼底彩照特征性病灶判读',
      tags: ['逐图判读', '眼底病灶', '病灶识别'],
      difficulty: imageForm.value.difficulty,
      explanation: imageForm.value.explanation
    }

    await createQuestion(payload)
    ElMessage.success('逐图题创建成功！已强绑定当前影像与病灶 ROI')
    emit('created')
    emit('update:modelValue', false)
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '出题失败')
  } finally {
    loading.value = false
  }
}

// 提交自定义指南挖空题
const submitCustomBlank = async () => {
  if (!blankForm.value.stem.includes('{{blank_1}}')) {
    ElMessage.warning('题干必须至少包含一个挖空占位符 {{blank_1}}')
    return
  }
  loading.value = true
  try {
    const blankConfig = [
      {
        index: 1,
        label: blankForm.value.blank1Label,
        expected: blankForm.value.blank1Answer.trim(),
        weight: 1.0
      }
    ]
    const alts: any[] = [
      blankForm.value.blank1Alts.split(/[,，、]/).map((s) => s.trim()).filter(Boolean)
    ]

    if (blankForm.value.stem.includes('{{blank_2}}')) {
      blankConfig.push({
        index: 2,
        label: blankForm.value.blank2Label,
        expected: blankForm.value.blank2Answer.trim(),
        weight: 1.0
      })
      alts.push(blankForm.value.blank2Alts.split(/[,，、]/).map((s) => s.trim()).filter(Boolean))
    }

    if (blankForm.value.stem.includes('{{blank_3}}')) {
      blankConfig.push({
        index: 3,
        label: blankForm.value.blank3Label,
        expected: blankForm.value.blank3Answer.trim(),
        weight: 1.0
      })
      alts.push(blankForm.value.blank3Alts.split(/[,，、]/).map((s) => s.trim()).filter(Boolean))
    }

    const payload: QuestionCreatePayload = {
      questionType: 'GUIDELINE_BLANK',
      caseId: props.caseId || null,
      stem: blankForm.value.stem,
      options: null,
      answer: blankConfig.map((b) => b.expected).join(' / '),
      acceptAlternatives: alts,
      blankConfig,
      sourceGuideline: blankForm.value.guideline,
      sourceSection: blankForm.value.section,
      tags: ['指南标准', '挖空考核'],
      difficulty: blankForm.value.difficulty,
      explanation: blankForm.value.explanation
    }

    await createQuestion(payload)
    ElMessage.success('指南挖空题创建成功！已录入题库')
    emit('created')
    emit('update:modelValue', false)
  } catch (err: any) {
    ElMessage.error(err.response?.data?.detail || err.message || '出题失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    title="临床智能出题工作台"
    size="560px"
    destroy-on-close
    @update:model-value="(v) => emit('update:modelValue', v)"
  >
    <div class="question-drawer-body">
      <el-alert
        title="出题系统内置临床指南防雷同算法：文本相似度高于 85% 将自动拦截，确保每道题目紧扣当前图像与权威指南。"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      />

      <el-tabs v-model="activeTab" class="question-tabs">
        <!-- 标签页 1：逐图题出题 -->
        <el-tab-pane label="逐图病灶题" name="image">
          <div class="case-meta-bar">
            <span>当前病例 ID：<strong>{{ caseId || '全局通用' }}</strong></span>
            <span v-if="imageUrl" class="img-badge">影像已绑定</span>
          </div>

          <el-form label-position="top" size="small">
            <el-form-item label="关联当前画布病灶标注 (ROI)">
              <el-select
                v-model="imageForm.selectedAnnotationId"
                placeholder="选择画面中的标注框自动提取 ROI 区域"
                clearable
                style="width: 100%"
                @change="onAnnotationSelected"
              >
                <el-option
                  v-for="(ann, idx) in currentAnnotations || []"
                  :key="ann.id"
                  :label="`#${idx + 1} [${ann.label || '病灶'}] - 坐标 [${ann.points?.map((p: any) => `${p.x},${p.y}`).join(';') || '无'}]`"
                  :value="ann.id"
                />
              </el-select>
              <div v-if="imageForm.roiBox" class="roi-box-tag">
                ROI 坐标：[x1: {{ imageForm.roiBox[0] }}, y1: {{ imageForm.roiBox[1] }}, x2: {{ imageForm.roiBox[2] }}, y2: {{ imageForm.roiBox[3] }}]
              </div>
            </el-form-item>

            <el-form-item label="题干描述 (Stem)" required>
              <el-input
                v-model="imageForm.stem"
                type="textarea"
                :rows="3"
                placeholder="请输入面向该图像特定病灶或区域的判读题目"
              />
            </el-form-item>

            <div class="options-grid">
              <el-form-item label="选项 A" required>
                <el-input v-model="imageForm.optionA" placeholder="选项 A 内容" />
              </el-form-item>
              <el-form-item label="选项 B" required>
                <el-input v-model="imageForm.optionB" placeholder="选项 B 内容" />
              </el-form-item>
              <el-form-item label="选项 C" required>
                <el-input v-model="imageForm.optionC" placeholder="选项 C 内容" />
              </el-form-item>
              <el-form-item label="选项 D" required>
                <el-input v-model="imageForm.optionD" placeholder="选项 D 内容" />
              </el-form-item>
            </div>

            <div class="two-col">
              <el-form-item label="标准正确答案" required>
                <el-radio-group v-model="imageForm.answer">
                  <el-radio-button value="A">A</el-radio-button>
                  <el-radio-button value="B">B</el-radio-button>
                  <el-radio-button value="C">C</el-radio-button>
                  <el-radio-button value="D">D</el-radio-button>
                </el-radio-group>
              </el-form-item>

              <el-form-item label="难度等级">
                <el-select v-model="imageForm.difficulty" style="width: 140px">
                  <el-option label="入门 (EASY)" value="EASY" />
                  <el-option label="中级 (MEDIUM)" value="MEDIUM" />
                  <el-option label="高级 (HARD)" value="HARD" />
                </el-select>
              </el-form-item>
            </div>

            <el-form-item label="临床判读依据与解析">
              <el-input
                v-model="imageForm.explanation"
                type="textarea"
                :rows="2"
                placeholder="学生作答后展示的临床指南依据与病理机制解析"
              />
            </el-form-item>

            <div class="submit-row">
              <el-button type="primary" :loading="loading" @click="submitImageQuestion">
                确认录入逐图题
              </el-button>
            </div>
          </el-form>
        </el-tab-pane>

        <!-- 标签页 2：临床指南模板生成 -->
        <el-tab-pane label="权威指南考点" name="template">
          <el-form label-position="top" size="small">
            <el-form-item label="选择系统权威临床指南标准">
              <el-select
                v-model="selectedTemplateCode"
                placeholder="请选择指南考点模板"
                style="width: 100%"
              >
                <el-option
                  v-for="tpl in templates"
                  :key="tpl.code"
                  :label="`${tpl.title} (${tpl.guideline})`"
                  :value="tpl.code"
                />
              </el-select>
            </el-form-item>

            <div v-if="currentSelectedTemplate" class="template-card">
              <div class="card-meta">
                <el-tag size="small" type="success">{{ currentSelectedTemplate.guideline }}</el-tag>
                <el-tag size="small" type="info">{{ currentSelectedTemplate.section }}</el-tag>
                <el-tag size="small">{{ currentSelectedTemplate.difficulty }}</el-tag>
              </div>
              <p class="card-stem"><strong>题干：</strong>{{ currentSelectedTemplate.stem }}</p>
              <div class="card-blanks">
                <div v-for="b in currentSelectedTemplate.blankConfig" :key="b.index" class="blank-chip">
                  <span class="idx">空 {{ b.index }}</span>
                  <span class="name">{{ b.label }}：</span>
                  <strong class="val">{{ b.expected }}</strong>
                </div>
              </div>
              <p class="card-exp"><strong>解析：</strong>{{ currentSelectedTemplate.explanation }}</p>
            </div>

            <div class="submit-row" style="margin-top: 20px">
              <el-button
                type="success"
                :loading="loading"
                :disabled="!selectedTemplateCode"
                @click="submitGenerateByTemplate"
              >
                基于该指南考点一键生成挖空题
              </el-button>
            </div>
          </el-form>
        </el-tab-pane>

        <!-- 标签页 3：自定义指南挖空题 -->
        <el-tab-pane label="自定义指南挖空" name="custom_blank">
          <el-form label-position="top" size="small">
            <div class="two-col">
              <el-form-item label="依据临床指南" required>
                <el-input v-model="blankForm.guideline" placeholder="例如：我国糖尿病视网膜病变指南(2022年)" />
              </el-form-item>
              <el-form-item label="指南章节/部分" required>
                <el-input v-model="blankForm.section" placeholder="例如：第二部分·临床分期" />
              </el-form-item>
            </div>

            <el-form-item label="挖空题干 (用 {{blank_1}}、{{blank_2}} 占位)" required>
              <el-input
                v-model="blankForm.stem"
                type="textarea"
                :rows="3"
                placeholder="在需要学员填写的关键数值或病征处使用 {{blank_1}} 占位符"
              />
            </el-form-item>

            <div class="blank-input-group">
              <div class="b-header">【第 1 空】配置</div>
              <div class="two-col">
                <el-input v-model="blankForm.blank1Label" placeholder="考点名称（如：出血象限数）" />
                <el-input v-model="blankForm.blank1Answer" placeholder="标准答案（如：4）" />
              </div>
              <el-input
                v-model="blankForm.blank1Alts"
                placeholder="同义词/容错词（逗号隔开，如：4, 4个, 四）"
                style="margin-top: 6px"
              />
            </div>

            <div v-if="blankForm.stem.includes('{{blank_2}}')" class="blank-input-group">
              <div class="b-header">【第 2 空】配置</div>
              <div class="two-col">
                <el-input v-model="blankForm.blank2Label" placeholder="考点名称（如：静脉串珠象限）" />
                <el-input v-model="blankForm.blank2Answer" placeholder="标准答案（如：2）" />
              </div>
              <el-input
                v-model="blankForm.blank2Alts"
                placeholder="同义词/容错词（逗号隔开，如：2, 2个, 二）"
                style="margin-top: 6px"
              />
            </div>

            <div v-if="blankForm.stem.includes('{{blank_3}}')" class="blank-input-group">
              <div class="b-header">【第 3 空】配置</div>
              <div class="two-col">
                <el-input v-model="blankForm.blank3Label" placeholder="考点名称（如：IRMA象限）" />
                <el-input v-model="blankForm.blank3Answer" placeholder="标准答案（如：1）" />
              </div>
              <el-input
                v-model="blankForm.blank3Alts"
                placeholder="同义词/容错词（逗号隔开，如：1, 1个, 一）"
                style="margin-top: 6px"
              />
            </div>

            <el-form-item label="解析与临床指南条文">
              <el-input
                v-model="blankForm.explanation"
                type="textarea"
                :rows="2"
                placeholder="填空判定后的临床条文依据解析"
              />
            </el-form-item>

            <div class="submit-row">
              <el-button type="primary" :loading="loading" @click="submitCustomBlank">
                确认录入指南挖空题
              </el-button>
            </div>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-drawer>
</template>

<style scoped>
.question-drawer-body {
  padding: 0 4px;
}
.case-meta-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: #181920;
  border-radius: 6px;
  margin-bottom: 14px;
  font-size: 13px;
  color: #cfd3dc;
}
.img-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: rgba(64, 158, 255, 0.15);
  color: #409eff;
  border: 1px solid rgba(64, 158, 255, 0.3);
}
.roi-box-tag {
  margin-top: 4px;
  font-size: 11px;
  color: #e6a23c;
  font-family: monospace;
}
.options-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}
.submit-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
.template-card {
  padding: 14px;
  background: #1c1d24;
  border: 1px solid #2e303d;
  border-radius: 8px;
}
.card-meta {
  display: flex;
  gap: 6px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.card-stem {
  font-size: 13px;
  line-height: 1.6;
  color: #ebeef5;
  margin-bottom: 10px;
}
.card-blanks {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 10px;
}
.blank-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  background: #252733;
  padding: 4px 8px;
  border-radius: 4px;
}
.blank-chip .idx {
  color: #409eff;
  font-weight: bold;
}
.blank-chip .val {
  color: #67c23a;
}
.card-exp {
  font-size: 12px;
  color: var(--hy-c-text-3, #909399);
  line-height: 1.5;
  margin: 0;
}
.blank-input-group {
  border: 1px dashed #363945;
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 12px;
  background: #16171d;
}
.b-header {
  font-size: 12px;
  color: #409eff;
  font-weight: 600;
  margin-bottom: 8px;
}
</style>

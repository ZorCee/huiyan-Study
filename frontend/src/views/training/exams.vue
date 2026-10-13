<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ExamApi, PracticeApi } from '@/api'
import type {
  ExamAudienceItem,
  ExamAudienceOptions,
  ExamAudienceScope,
  ExamCaseOption,
  ExamPaper,
  ExamPreview
} from '@/api/exam'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const loading = ref(false)
const papers = ref<ExamPaper[]>([])
const cases = ref<ExamCaseOption[]>([])
const dialog = ref(false)
const saving = ref(false)

const form = reactive({
  title: '',
  durationMinutes: 60,
  passScore: 60,
  allowBack: false,
  pickMode: 'SELECTED' as 'SELECTED' | 'DRAW',
  category: '',
  difficulty: '',
  caseIds: [] as number[],
  questionCount: 3,
  audienceScope: 'ALL' as ExamAudienceScope,
  audienceValues: [] as string[],
  audienceIds: [] as number[]
})

const audience = ref<ExamAudienceOptions | null>(null)
const SCOPE_OPTIONS: { value: ExamAudienceScope; label: string }[] = [
  { value: 'ALL', label: '全体学员' },
  { value: 'YEAR', label: '年级' },
  { value: 'BATCH', label: '轮转批次' },
  { value: 'GROUP', label: '带教组' },
  { value: 'PEOPLE', label: '指定学员' }
]
const SCOPE_FIELD = { YEAR: 'studyYear', BATCH: 'rotationBatch', GROUP: 'mentorGroup' } as const

const scopeItems = computed<ExamAudienceItem[]>(() => {
  const data = audience.value
  if (!data) return []
  if (form.audienceScope === 'YEAR') return data.years
  if (form.audienceScope === 'BATCH') return data.batches
  if (form.audienceScope === 'GROUP') return data.groups
  return []
})

const audienceCount = computed(() => {
  const data = audience.value
  if (!data) return 0
  const scope = form.audienceScope
  if (scope === 'ALL') return data.total
  if (scope === 'PEOPLE') return form.audienceIds.length
  const field = SCOPE_FIELD[scope]
  const picked = new Set(form.audienceValues)
  return data.students.filter((s) => picked.has((s[field] || '').trim())).length
})

watch(
  () => form.audienceScope,
  () => {
    form.audienceValues = []
    form.audienceIds = []
  }
)

const preview = ref<ExamPreview | null>(null)
const previewLoading = ref(false)
const expandedCase = ref<number | null>(null)
let previewToken = 0

const drawMatches = computed(() =>
  cases.value.filter(
    (item) =>
      (!form.category || item.category === form.category) &&
      (!form.difficulty || item.difficulty === form.difficulty)
  )
)

const previewIds = computed(() =>
  form.pickMode === 'SELECTED' ? form.caseIds : drawMatches.value.slice(0, 20).map((item) => item.id)
)

const drawWithOwn = computed(
  () => preview.value?.cases.filter((item) => item.ownCount > 0).length ?? 0
)

watch(
  [previewIds, dialog],
  async ([ids, open]) => {
    const token = ++previewToken
    if (!open || !ids.length) {
      preview.value = null
      return
    }
    previewLoading.value = true
    try {
      const data = await ExamApi.previewExam([...ids])
      if (token === previewToken) preview.value = data
    } catch {
      if (token === previewToken) preview.value = null
    } finally {
      if (token === previewToken) previewLoading.value = false
    }
  },
  { deep: true }
)

const previewFor = (caseId: number) => preview.value?.cases.find((item) => item.caseId === caseId)

const caseLabel = (caseId: number) => {
  const item = cases.value.find((c) => c.id === caseId)
  return item ? `${item.caseNo} ${item.title}` : `病例 ${caseId}`
}

const studentLabel = (s: ExamAudienceOptions['students'][number]) => {
  const parts = [s.studyYear, s.rotationBatch, s.mentorGroup].filter(Boolean)
  return parts.length ? `${s.name}（${parts.join(' / ')}）` : `${s.name}（未分组）`
}

const load = async () => {
  loading.value = true
  try {
    papers.value = (await ExamApi.listExams()) || []
  } finally {
    loading.value = false
  }
}

const openCreate = async () => {
  form.title = ''
  form.durationMinutes = 60
  form.passScore = 60
  form.allowBack = false
  form.pickMode = 'SELECTED'
  form.category = ''
  form.difficulty = ''
  form.caseIds = []
  form.questionCount = 3
  form.audienceScope = 'ALL'
  form.audienceValues = []
  form.audienceIds = []
  expandedCase.value = null
  dialog.value = true
  const [caseList, audienceData] = await Promise.all([
    cases.value.length ? Promise.resolve(cases.value) : ExamApi.caseOptions(),
    ExamApi.audienceOptions()
  ])
  cases.value = caseList || []
  audience.value = audienceData || null
}

const publish = async () => {
  if (!form.title.trim()) {
    ElMessage.warning('请填写考试名称')
    return
  }
  if (form.pickMode === 'SELECTED' && !form.caseIds.length) {
    ElMessage.warning('请至少选择一份病例')
    return
  }
  if (form.audienceScope === 'PEOPLE' && !form.audienceIds.length) {
    ElMessage.warning('请选择受考学员')
    return
  }
  if (!['ALL', 'PEOPLE'].includes(form.audienceScope) && !form.audienceValues.length) {
    ElMessage.warning('请选择受考对象')
    return
  }
  if (audience.value && !audienceCount.value) {
    ElMessage.warning('所选受考对象里没有学员')
    return
  }
  saving.value = true
  try {
    await ExamApi.createExam({
      title: form.title.trim(),
      durationMinutes: form.durationMinutes,
      passScore: form.passScore,
      allowBack: form.allowBack,
      pickMode: form.pickMode,
      category: form.category,
      difficulty: form.difficulty,
      caseIds: form.caseIds,
      questionCount: form.questionCount,
      audienceScope: form.audienceScope,
      audienceValues: form.audienceValues,
      audienceIds: form.audienceIds
    })
    dialog.value = false
    await load()
  } finally {
    saving.value = false
  }
}

const collect = async (row: ExamPaper) => {
  try {
    await ElMessageBox.confirm(
      '收卷后未交的题目按已保存内容计分，没写的按未答。收卷后才公布答案，并可以导出成绩。',
      `收卷「${row.title}」`,
      { type: 'warning', confirmButtonText: '收卷' }
    )
  } catch {
    return
  }
  await ExamApi.collectExam(row.id)
  await load()
}

const resetting = ref('')
const resetAttempt = async (row: ExamPaper, studentId: number, name: string) => {
  try {
    await ElMessageBox.confirm(
      `${name} 进入「${row.title}」后没有作答，到时被系统补交了空白卷。重置后会清掉这份空白卷，学员可以重新进入，考试时间重新计算。`,
      '重置作答',
      { type: 'warning', confirmButtonText: '重置' }
    )
  } catch {
    return
  }
  resetting.value = `${row.id}-${studentId}`
  try {
    await ExamApi.resetExamAttempt(row.id, studentId)
    ElMessage.success(`已重置，${name} 可以重新进入考试`)
    await load()
  } finally {
    resetting.value = ''
  }
}

const download = (row: ExamPaper) => {
  ExamApi.downloadGrades(row.id, `${row.title}-成绩.csv`)
}

const remove = async (row: ExamPaper) => {
  try {
    await ElMessageBox.confirm(`删除「${row.title}」？还没有学员进入。`, '删除考试', { type: 'warning' })
  } catch {
    return
  }
  await ExamApi.removeExam(row.id)
  await load()
}

onMounted(load)
</script>

<template>
  <div class="exam-page">
    <div class="toolbar">
      <div>
        <h2>正式考核与试卷</h2>
        <p>指定病例，或按病种和难度抽一套题。全班同一套。收卷后统一导出成绩。</p>
      </div>
      <el-button type="primary" @click="openCreate">发布考试</el-button>
    </div>

    <el-table v-loading="loading" :data="papers" border stripe>
      <el-table-column prop="title" label="考试" min-width="140" />
      <el-table-column label="发起人" width="110">
        <template #default="{ row }">{{ row.publisherName || '—' }}</template>
      </el-table-column>
      <el-table-column label="题目" min-width="180">
        <template #default="{ row }">
          {{ row.questionCount }} 题
          <span v-if="row.caseNos?.length" class="muted">{{ row.caseNos.join('、') }}</span>
        </template>
      </el-table-column>
      <el-table-column label="受考对象" min-width="150">
        <template #default="{ row }">
          <el-tag size="small" :type="row.audienceScope && row.audienceScope !== 'ALL' ? 'primary' : 'info'">
            {{ row.audienceLabel || '全体学员' }}
          </el-tag>
          <span v-if="row.audienceCount" class="muted">{{ row.audienceCount }} 人</span>
        </template>
      </el-table-column>
      <el-table-column label="时间" width="90">
        <template #default="{ row }">{{ row.durationMinutes }} 分钟</template>
      </el-table-column>
      <el-table-column label="合格线" width="80">
        <template #default="{ row }">{{ row.passScore }}</template>
      </el-table-column>
      <el-table-column label="返回上一题" width="110">
        <template #default="{ row }">{{ row.allowBack ? '允许' : '不允许' }}</template>
      </el-table-column>
      <el-table-column label="交卷" width="110">
        <template #default="{ row }">{{ row.handedCount }} / {{ row.enteredCount }} 人</template>
      </el-table-column>
      <el-table-column label="作答学员" min-width="180">
        <template #default="{ row }">
          <div v-if="row.participants?.length" class="participants">
            <span v-for="item in row.participants" :key="item.userId || item.name" class="participant">
              {{ item.name }}
              <el-tag
                size="small"
                :type="item.state === '已交卷' ? 'success' : item.state === '超时未作答' ? 'danger' : 'warning'"
              >
                {{ item.state }}
              </el-tag>
              <el-button
                v-if="row.status === 'OPEN' && item.state === '超时未作答' && item.userId"
                link
                type="primary"
                size="small"
                :loading="resetting === `${row.id}-${item.userId}`"
                @click="resetAttempt(row, item.userId, item.name)"
              >
                重置
              </el-button>
            </span>
          </div>
          <span v-else class="muted">还没有学员进入</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="row.status === 'CLOSED' ? 'info' : 'success'">
            {{ row.status === 'CLOSED' ? '已收卷' : '进行中' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.status === 'OPEN'" size="small" type="primary" @click="collect(row)">
            收卷
          </el-button>
          <el-button v-else size="small" @click="download(row)">导出成绩</el-button>
          <el-button
            v-if="row.status === 'OPEN' && !row.enteredCount"
            size="small"
            type="danger"
            plain
            @click="remove(row)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialog" title="发布考试" width="640px">
      <el-form label-width="120px">
        <el-form-item label="考试名称">
          <el-input v-model="form.title" maxlength="64" placeholder="例如：眼底病月考" />
        </el-form-item>
        <el-form-item label="发起人">
          <el-input :model-value="userStore.displayName" disabled />
        </el-form-item>
        <el-form-item label="考试时间">
          <el-input-number v-model="form.durationMinutes" :min="1" :max="240" />
          <span class="unit">分钟，从学员进入时起算</span>
        </el-form-item>
        <el-form-item label="合格分数">
          <el-input-number v-model="form.passScore" :min="0" :max="100" />
          <span class="unit">整卷平均分</span>
        </el-form-item>
        <el-form-item label="返回上一题">
          <el-switch v-model="form.allowBack" active-text="允许" inactive-text="不允许" />
        </el-form-item>
        <el-form-item label="受考对象">
          <div class="audience">
            <el-radio-group v-model="form.audienceScope" size="small">
              <el-radio-button v-for="item in SCOPE_OPTIONS" :key="item.value" :value="item.value">
                {{ item.label }}
              </el-radio-button>
            </el-radio-group>
            <el-select
              v-if="form.audienceScope === 'PEOPLE'"
              v-model="form.audienceIds"
              multiple
              filterable
              collapse-tags
              collapse-tags-tooltip
              placeholder="搜索姓名，可多选"
              style="width: 100%"
            >
              <el-option
                v-for="s in audience?.students || []"
                :key="s.id"
                :label="studentLabel(s)"
                :value="s.id"
              />
            </el-select>
            <template v-else-if="form.audienceScope !== 'ALL'">
              <el-select
                v-if="scopeItems.length"
                v-model="form.audienceValues"
                multiple
                placeholder="可多选"
                style="width: 100%"
              >
                <el-option
                  v-for="item in scopeItems"
                  :key="item.value"
                  :label="`${item.label}（${item.count} 人）`"
                  :value="item.value"
                />
              </el-select>
              <p v-else class="hint warn">
                还没有学员填写这一项分组，请先到「管理与设置 → 班级与学员维护」里维护，或改用「指定学员」。
              </p>
            </template>
            <p class="hint" :class="{ warn: audience && !audienceCount }">
              共 <strong>{{ audienceCount }}</strong> 名学员会看到这场考试
              <template v-if="form.audienceScope !== 'ALL'">，其他学员在考试列表里看不到</template>
            </p>
          </div>
        </el-form-item>
        <el-form-item label="组卷方式">
          <el-radio-group v-model="form.pickMode">
            <el-radio value="SELECTED">指定病例</el-radio>
            <el-radio value="DRAW">按病种、难度抽题</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.pickMode === 'SELECTED'" label="病例">
          <el-select
            v-model="form.caseIds"
            multiple
            filterable
            placeholder="按顺序选择，全班同一套"
            style="width: 100%"
          >
            <el-option
              v-for="item in cases"
              :key="item.id"
              :label="`${item.caseNo} ${item.title} · ${item.categoryText} · ${item.difficultyText}`"
              :value="item.id"
            />
          </el-select>
          <ul v-if="form.caseIds.length" v-loading="previewLoading" class="case-preview">
            <li v-for="id in form.caseIds" :key="id">
              <div class="case-row">
                <span class="case-name">{{ caseLabel(id) }}</span>
                <template v-if="previewFor(id)">
                  <el-tag v-if="previewFor(id)!.ownCount" size="small" type="success">
                    含 {{ previewFor(id)!.ownCount }} 道专属题
                  </el-tag>
                  <el-tag v-else size="small" type="warning">无专属题</el-tag>
                  <el-button
                    link
                    type="primary"
                    size="small"
                    :aria-expanded="expandedCase === id"
                    @click="expandedCase = expandedCase === id ? null : id"
                  >
                    {{ expandedCase === id ? '收起' : '看题目' }}
                  </el-button>
                </template>
              </div>
              <p v-if="previewFor(id) && !previewFor(id)!.ownCount" class="hint warn">
                该病例没有关联题目，将用通用题补齐
              </p>
              <ol v-if="expandedCase === id && previewFor(id)" class="question-list">
                <li v-for="q in previewFor(id)!.questions" :key="q.id">
                  <el-tag size="small" :type="q.source === 'OWN' ? 'success' : 'info'">
                    {{ q.source === 'OWN' ? '专属' : '通用' }} · {{ q.typeText }}
                  </el-tag>
                  <span>{{ q.stem || '（题干为空）' }}</span>
                </li>
                <li v-if="previewFor(id)!.legacyCount" class="muted-item">
                  <el-tag size="small" type="info">常规题</el-tag>
                  <span>随机 {{ previewFor(id)!.legacyCount }} 道，学员进入时抽取，每人可能不同</span>
                </li>
              </ol>
            </li>
          </ul>
        </el-form-item>
        <template v-else>
          <el-form-item label="病种">
            <el-select v-model="form.category" clearable placeholder="全部病种" style="width: 100%">
              <el-option
                v-for="item in PracticeApi.CATEGORY_FILTERS"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="难度">
            <el-select v-model="form.difficulty" clearable placeholder="全部难度" style="width: 100%">
              <el-option
                v-for="item in PracticeApi.DIFFICULTY_FILTERS"
                :key="item.value"
                :label="item.label"
                :value="item.value"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="题数">
            <el-input-number v-model="form.questionCount" :min="1" :max="20" />
            <span class="unit">抽出后全班用同一套</span>
          </el-form-item>
          <el-form-item label="题库情况">
            <p class="hint" :class="{ warn: !drawMatches.length }">
              匹配 {{ drawMatches.length }} 份病例<template v-if="preview">
                ，其中 {{ drawWithOwn }} 份有专属题</template
              ><template v-if="drawMatches.length > 20">（只统计前 20 份）</template>。具体抽到哪些病例在发布时确定。
            </p>
          </el-form-item>
        </template>
      </el-form>
      <section
        v-if="form.pickMode === 'SELECTED' && preview && preview.cases.length"
        class="paper-summary"
        aria-label="整卷预览"
      >
        <h3>整卷预览</h3>
        <p>
          {{ preview.cases.length }} 个病例，文字题共 {{ preview.totalQuestions }} 道：
          专属题 {{ preview.ownTotal }}，通用题 {{ preview.genericTotal }}，常规题（随机）{{ preview.legacyTotal }}
        </p>
        <div class="type-tags">
          <el-tag v-for="(count, name) in preview.typeCounts" :key="name" size="small" type="info">
            {{ name }} {{ count }}
          </el-tag>
        </div>
      </section>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="publish">发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.exam-page {
  min-height: 100%;
  padding: 20px 24px 40px;
  background: var(--hy-c-fill, #f5f7fa);
}
.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}
.toolbar h2 {
  margin: 0 0 6px;
  font-size: 18px;
  color: var(--hy-c-text, #1d2129);
}
.toolbar p,
.muted,
.unit {
  color: var(--hy-c-text-3, #86909c);
  font-size: 13px;
}
.toolbar p {
  margin: 0;
}
.muted {
  margin-left: 8px;
}
.unit {
  margin-left: 8px;
}
.participants {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
}
.participant {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.audience {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}
.hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--hy-c-text-3, #86909c);
}
.hint strong {
  color: var(--hy-c-text, #1d2129);
}
.hint.warn {
  color: var(--el-color-warning, #e6a23c);
}
.case-preview {
  width: 100%;
  margin: 8px 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.case-preview > li {
  padding: 6px 10px;
  border: 1px solid var(--el-border-color-lighter, #ebeef5);
  border-radius: 6px;
}
.case-row {
  display: flex;
  align-items: center;
  gap: 8px;
  line-height: 1.6;
}
.case-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.question-list {
  margin: 6px 0 2px;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  line-height: 1.6;
}
.question-list li span {
  margin-left: 6px;
}
.muted-item {
  color: var(--hy-c-text-3, #86909c);
}
.paper-summary {
  margin: 4px 0 0 120px;
  padding: 10px 12px;
  border-radius: 6px;
  background: var(--el-fill-color-light, #f5f7fa);
  font-size: 13px;
}
.paper-summary h3 {
  margin: 0 0 4px;
  font-size: 13px;
}
.paper-summary p {
  margin: 0 0 6px;
  color: var(--hy-c-text-2, #4e5969);
}
.type-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>

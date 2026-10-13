<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowDown,
  ArrowUp,
  QuestionFilled,
  Back,
  Close,
  RefreshLeft,
  Check,
  Filter
} from '@element-plus/icons-vue'
import { ExamApi, PracticeApi, RotationApi } from '@/api'
import type { ExamPaper } from '@/api/exam'
import type {
  CaseOptionItem,
  GroupSummary,
  PendingCaseItem,
  RotationTask,
  StudentHome,
  StudentProgress,
  TeacherHome
} from '@/api/rotation'
import { CATEGORY_OPTIONS, DIFFICULTY_OPTIONS } from '@/api/case-browse'
import { useUserStore } from '@/stores/user'
import { actorLabel } from '@/utils/actor'
import { usePendingReviewCount } from '@/composables/usePendingReviewCount'
import StudentDrilldownDrawer from './components/StudentDrilldownDrawer.vue'
import WeakCaseListDialog from './components/WeakCaseListDialog.vue'
import KpiDrilldownDialog from './components/KpiDrilldownDialog.vue'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const isTeacher = computed(() => userStore.isAdmin || userStore.isDoctor)

const loading = ref(false)
const student = ref<StudentHome | null>(null)
const teacher = ref<TeacherHome | null>(null)

const caseId = ref<number | undefined>()
const caseTier = ref<'REQUIRED' | 'EXTENSION'>('REQUIRED')
const caseScope = ref<'ALL' | 'YEAR' | 'GROUP'>('ALL')
const caseScopeValue = ref('')
const resourceId = ref<number | undefined>()
const knowledgeTitle = ref('')
const caseOptions = ref<CaseOptionItem[]>([])
const pendingCases = ref<PendingCaseItem[]>([])
const optionsLoaded = ref(false)
const caseCategoryFilter = ref('')
const caseDifficultyFilter = ref('')
const caseGradeFilter = ref('')
const DR_GRADE_CHOICES = ['0', '1', '2', '3', '4']
const matchesCaseFilters = (item: CaseOptionItem) =>
  (!caseCategoryFilter.value || item.category === caseCategoryFilter.value) &&
  (!caseDifficultyFilter.value || item.difficulty === caseDifficultyFilter.value) &&
  (!caseGradeFilter.value || item.goldDrGrade === caseGradeFilter.value)
const filteredCaseOptions = computed(() => caseOptions.value.filter(matchesCaseFilters))
const filteredPendingCases = computed(() => pendingCases.value.filter(matchesCaseFilters))
const caseFiltersActive = computed(
  () => !!(caseCategoryFilter.value || caseDifficultyFilter.value || caseGradeFilter.value)
)
const goCaseLibrary = () => router.push('/training/cases')
const resourceOptions = ref<{ id: number; label: string }[]>([])
const dueDraft = ref('')
const passDraft = ref(60)
const titleDraft = ref('')
const yearFilter = ref('')
const batchFilter = ref('')
const mentorFilter = ref('')
const activeTeacherTab = ref('monitor')
const { pendingReviewCount, refreshPendingReviewCount } = usePendingReviewCount()
const openExams = ref<ExamPaper[]>([])

const load = async () => {
  loading.value = true
  try {
    const data = await RotationApi.getHome()
    if (data.role === 'teacher') {
      teacher.value = data
      student.value = null
      titleDraft.value = data.rotation?.title || ''
      dueDraft.value = data.rotation?.dueOn || ''
      passDraft.value = data.rotation?.passScore ?? 60
      syncFromQuery()
    } else {
      student.value = data
      teacher.value = null
    }
  } finally {
    loading.value = false
  }
}

const loadOptions = async () => {
  if (!isTeacher.value) return
  const data = await RotationApi.getOptions()
  caseOptions.value = data.cases || []
  pendingCases.value = data.pendingCases || []
  resourceOptions.value = data.resources || []
  optionsLoaded.value = true
}

const loadPendingReviews = async () => {
  if (!isTeacher.value) return
  await refreshPendingReviewCount()
}

const loadOpenExams = async () => {
  if (isTeacher.value) {
    openExams.value = []
    return
  }
  try {
    const rows = (await ExamApi.listExams()) || []
    openExams.value = rows.filter(
      (paper) =>
        paper.status === 'OPEN' &&
        paper.mineStatus !== 'HANDED' &&
        paper.mineStatus !== 'TIMEOUT_BLANK'
    )
  } catch {
    openExams.value = []
  }
}

onMounted(async () => {
  await load()
  await Promise.all([loadOptions(), loadPendingReviews(), loadOpenExams()])
})

const startCase = async (task: RotationTask) => {
  if (!task.caseId) return
  const rec = await PracticeApi.startPractice({ caseId: task.caseId, mode: 'SELECTED' })
  router.push({
    path: '/practice/workstation',
    query: { sessionId: String(rec.id), caseId: String(task.caseId), from: 'rotation' }
  })
}

const markLearned = async (task: RotationTask) => {
  student.value = await RotationApi.markLearned(task.id)
  ElMessage.success('已记入本轮转进度')
}

const openKnowledge = (task: RotationTask) => {
  if (task.resourceId) {
    router.push({
      path: '/training/learning',
      query: { resourceId: String(task.resourceId), taskId: String(task.id) }
    })
    return
  }
  router.push('/training/learning')
}

const openAssigned = (task: RotationTask) => {
  if (task.kind === 'CASE' && task.caseNo) {
    router.push({ path: '/training/cases', query: { keyword: task.caseNo } })
    return
  }
  if (task.resourceId) {
    router.push({ path: '/training/learning', query: { resourceId: String(task.resourceId) } })
  }
}

const taskTitle = (taskId: number) =>
  teacher.value?.tasks.find((item) => item.id === taskId)?.title || '任务'

const uniqueLabels = (values: string[]) => [...new Set(values.filter(Boolean))]

const yearOptions = computed(() => uniqueLabels((teacher.value?.students || []).map((row) => row.studyYear)))
const batchOptions = computed(() => uniqueLabels((teacher.value?.students || []).map((row) => row.rotationBatch)))
const mentorOptions = computed(() => uniqueLabels((teacher.value?.students || []).map((row) => row.mentorGroup)))

const matchGroup = (row: { studyYear: string; rotationBatch: string; mentorGroup: string }) => {
  if (yearFilter.value && row.studyYear !== yearFilter.value) return false
  if (batchFilter.value && row.rotationBatch !== batchFilter.value) return false
  if (mentorFilter.value && row.mentorGroup !== mentorFilter.value) return false
  return true
}

const filteredStudents = computed(() => (teacher.value?.students || []).filter(matchGroup))

// 组卡片区展示：按下拉框选中的年级和批次收窄，但不因选择了带教组而隐藏其它组卡片，确保用户可随时切换
const visibleGroups = computed(() => {
  const all = teacher.value?.groups || []
  return all.filter((g) => {
    if (yearFilter.value && g.studyYear !== yearFilter.value && g.studyYear !== '未分组') return false
    if (batchFilter.value && g.rotationBatch !== batchFilter.value && g.rotationBatch !== '未分组') return false
    return true
  })
})

const isGroupSelected = (group: GroupSummary) => {
  const gYear = group.studyYear === '未分组' ? '' : group.studyYear
  const gBatch = group.rotationBatch === '未分组' ? '' : group.rotationBatch
  const gMentor = group.mentorGroup === '未分组' ? '' : group.mentorGroup
  return (
    yearFilter.value === gYear &&
    batchFilter.value === gBatch &&
    mentorFilter.value === gMentor
  )
}

const isAnyFilterActive = computed(() => !!(yearFilter.value || batchFilter.value || mentorFilter.value))

// 状态同步到路由 Query（支持浏览器前进后退、刷新保持、收藏分享）
const syncToQuery = (replace = false) => {
  const q = { ...route.query }
  if (yearFilter.value) q.studyYear = yearFilter.value; else delete q.studyYear
  if (batchFilter.value) q.rotationBatch = batchFilter.value; else delete q.rotationBatch
  if (mentorFilter.value) q.mentorGroup = mentorFilter.value; else delete q.mentorGroup
  if (activeTeacherTab.value) q.tab = activeTeacherTab.value

  if (replace) {
    router.replace({ query: q })
  } else {
    router.push({ query: q })
  }
}

// 从路由 Query 同步回响应式变量
const syncFromQuery = () => {
  const q = route.query
  const qYear = typeof q.studyYear === 'string' ? q.studyYear : ''
  const qBatch = typeof q.rotationBatch === 'string' ? q.rotationBatch : ''
  const qMentor = typeof q.mentorGroup === 'string' ? q.mentorGroup : ''
  const qTab = typeof q.tab === 'string' ? q.tab : ''

  if (qYear !== yearFilter.value) yearFilter.value = qYear
  if (qBatch !== batchFilter.value) batchFilter.value = qBatch
  if (qMentor !== mentorFilter.value) mentorFilter.value = qMentor
  if (qTab && qTab !== activeTeacherTab.value) activeTeacherTab.value = qTab
}

// 监听路由 query 变动（用户点击浏览器后退 / 前进键）
watch(
  () => route.query,
  () => {
    syncFromQuery()
  }
)

const onDropdownFilterChange = () => {
  syncToQuery(false)
}

const onTabChange = (name: string | number) => {
  activeTeacherTab.value = String(name)
  syncToQuery(true)
}

const filterByGroup = (group: GroupSummary) => {
  const gYear = group.studyYear === '未分组' ? '' : group.studyYear
  const gBatch = group.rotationBatch === '未分组' ? '' : group.rotationBatch
  const gMentor = group.mentorGroup === '未分组' ? '' : group.mentorGroup

  if (isGroupSelected(group)) {
    // 二次点击取消筛选，返回全部学员
    clearAllGroupFilters(true)
    ElMessage.info('已取消带教组筛选，返回全部学员')
    return
  }

  // 选中该组 / 切换到该组
  yearFilter.value = gYear
  batchFilter.value = gBatch
  mentorFilter.value = gMentor
  syncToQuery(false)
  ElMessage.success(`已筛选【${group.mentorGroup || '带教组'}】学员进度列表`)
}

const clearAllGroupFilters = (pushHistory = true) => {
  yearFilter.value = ''
  batchFilter.value = ''
  mentorFilter.value = ''
  if (pushHistory) {
    syncToQuery(false)
  }
}

const clearFilter = (type: 'year' | 'batch' | 'mentor') => {
  if (type === 'year') yearFilter.value = ''
  else if (type === 'batch') batchFilter.value = ''
  else if (type === 'mentor') mentorFilter.value = ''
  syncToQuery(false)
}

const selectBreadcrumbYear = () => {
  batchFilter.value = ''
  mentorFilter.value = ''
  syncToQuery(false)
}

const selectBreadcrumbBatch = () => {
  mentorFilter.value = ''
  syncToQuery(false)
}

const classSummary = computed(() => {
  const rows = teacher.value?.students || []
  const practice = rows.reduce((sum, row) => sum + (row.practiceCount || 0), 0)
  const cases = rows.reduce((sum, row) => sum + (row.completedCases || 0), 0)
  const seconds = rows.reduce((sum, row) => sum + (row.studySeconds || 0), 0)
  const scoreSum = rows.reduce((sum, row) => sum + (row.avgScore || 0) * (row.practiceCount || 0), 0)
  return {
    students: rows.length,
    practiced: rows.filter((row) => (row.practiceCount || 0) > 0).length,
    practice,
    cases,
    avg: practice ? scoreSum / practice : 0,
    seconds
  }
})

const formatMinutes = (seconds: number) => {
  if (!seconds) return '0 分钟'
  if (seconds < 60) return '不足 1 分钟'
  return `${Math.round(seconds / 60)} 分钟`
}

const drawerOpen = ref(false)
const focusStudent = ref<StudentProgress | null>(null)

const openStudent = (row: StudentProgress) => {
  focusStudent.value = row
  drawerOpen.value = true
}

const onGroupUpdated = async () => {
  const home = await RotationApi.getHome()
  if (home.role === 'teacher') {
    teacher.value = home
    if (focusStudent.value) {
      const latest = home.students.find((item) => item.userId === focusStudent.value?.userId)
      if (latest) focusStudent.value = latest
    }
  }
}

// KPI 穿透状态
const kpiModalVisible = ref(false)
const kpiModalType = ref<'students' | 'practice' | 'avgScore' | 'studyHours'>('students')
const kpiModalTitle = ref('')

const openKpiModal = (type: 'students' | 'practice' | 'avgScore' | 'studyHours') => {
  kpiModalType.value = type
  if (type === 'students') kpiModalTitle.value = '全班学员名单及作答情况'
  else if (type === 'practice') kpiModalTitle.value = '全班练习交卷台账明细'
  else if (type === 'avgScore') kpiModalTitle.value = '练习成绩分布与逐人达标'
  else if (type === 'studyHours') kpiModalTitle.value = '学员有效在机学时排行'
  kpiModalVisible.value = true
}

const onSelectStudentFromKpi = (stu: StudentProgress) => {
  kpiModalVisible.value = false
  openStudent(stu)
}

// 常见漏诊误诊穿透状态
const weakModalVisible = ref(false)
const weakModalLabel = ref('')
const weakModalType = ref<'missed' | 'false_positive' | ''>('')
const weakModalGroup = ref<GroupSummary | null>(null)
const weakModalTitle = ref('')

const openGroupWeak = (group: GroupSummary, label: string, type: 'missed' | 'false_positive') => {
  weakModalGroup.value = group
  weakModalLabel.value = label
  weakModalType.value = type
  weakModalTitle.value = `【${group.mentorGroup || '带教组'}】${label} ${type === 'missed' ? '漏诊' : '误诊'}明细`
  weakModalVisible.value = true
}


const openTaskWorkstation = (snap: any) => {
  if (snap.caseId && snap.sessionId) {
    router.push({
      path: '/training/practice/workstation',
      query: {
        caseId: String(snap.caseId),
        sessionId: String(snap.sessionId),
        view: 'report'
      }
    })
  } else if (snap.caseId) {
    router.push({
      path: '/training/reading',
      query: { caseId: String(snap.caseId) }
    })
  }
}

const saveRotation = async () => {
  teacher.value = await RotationApi.updateRotation({
    title: titleDraft.value,
    dueOn: dueDraft.value,
    passScore: passDraft.value
  })
  ElMessage.success('轮转要求已保存')
}

const assignTargets = computed(() =>
  (caseScope.value === 'YEAR' ? yearOptions.value : mentorOptions.value).filter((item) => item !== '未分组')
)

const addCase = async () => {
  if (!caseId.value) {
    ElMessage.warning('请选择病例')
    return
  }
  if (caseScope.value !== 'ALL' && !caseScopeValue.value) {
    ElMessage.warning(caseScope.value === 'YEAR' ? '请选择年级' : '请选择轮转组')
    return
  }
  teacher.value = await RotationApi.addTask({
    kind: 'CASE',
    caseId: caseId.value,
    passScore: passDraft.value,
    tier: caseTier.value,
    scope: caseScope.value,
    scopeValue: caseScope.value === 'ALL' ? '' : caseScopeValue.value
  })
  caseId.value = undefined
  ElMessage.success(caseTier.value === 'EXTENSION' ? '已标为拓展病例' : '已标为必做病例')
}

const movedTaskId = ref(0)
let movedFlash = 0
const taskRowClass = ({ row }: { row: RotationTask }) =>
  row.id === movedTaskId.value ? 'is-just-moved' : ''

const moveTask = async (index: number, delta: number) => {
  const rows = [...(teacher.value?.tasks || [])]
  const next = index + delta
  if (next < 0 || next >= rows.length) return
  const [item] = rows.splice(index, 1)
  rows.splice(next, 0, item)
  teacher.value = await RotationApi.reorderTasks(rows.map((row) => row.id))
  movedTaskId.value = item.id
  window.clearTimeout(movedFlash)
  movedFlash = window.setTimeout(() => {
    if (movedTaskId.value === item.id) movedTaskId.value = 0
  }, 3200)
  await nextTick()
  document.querySelector('.task-order-table .is-just-moved')?.scrollIntoView({ block: 'nearest' })
}

const arrangeBySpectrum = async () => {
  teacher.value = await RotationApi.arrangeTasks()
  ElMessage.success('已按从正常到重症排列，必做在前、拓展在后')
}

const addKnowledge = async () => {
  if (!resourceId.value && !knowledgeTitle.value.trim()) {
    ElMessage.warning('请选择资料或填写知识点')
    return
  }
  teacher.value = await RotationApi.addTask({
    kind: 'KNOWLEDGE',
    resourceId: resourceId.value,
    title: knowledgeTitle.value.trim()
  })
  resourceId.value = undefined
  knowledgeTitle.value = ''
  ElMessage.success('已加入本轮转')
}

const removeTask = async (task: RotationTask) => {
  await ElMessageBox.confirm(`撤下「${task.title}」？已有的练习成绩不会删除。`, '撤下必做', {
    type: 'warning'
  })
  teacher.value = await RotationApi.removeTask(task.id)
}

const statusType = (task: { status: string; overdue?: boolean; dueToday?: boolean }) => {
  if (task.status === 'DONE' || task.status === 'LEARNED') return 'success'
  if (task.overdue || task.status === 'SHORT') return 'danger'
  if (task.dueToday || task.status === 'DOING') return 'warning'
  return 'info'
}
</script>

<template>
  <div v-loading="loading" class="home-page">
    <template v-if="student">
      <header class="page-head">
        <div>
          <h2>今日学习任务</h2>
          <p>
            {{ student.studyYear }} · {{ student.rotationBatch }} · {{ student.mentorGroup }}。
            <template v-if="actorLabel(student.groupEditorName, student.groupEditorRole)">
              分组由 {{ actorLabel(student.groupEditorName, student.groupEditorRole) }}
              <template v-if="student.groupEditedAt">于 {{ student.groupEditedAt }}</template>
              填写。
            </template>
            {{ student.rotation?.title || '本轮转' }}。必做计入进度。拓展病例是老师另外推荐的，做完不改变必做进度。
          </p>
        </div>
      </header>

      <section v-if="openExams.length" class="block exam-callout">
        <h3>正式考试</h3>
        <div v-for="paper in openExams" :key="paper.id" class="exam-call">
          <div>
            <strong>{{ paper.title }}</strong>
            <p>
              {{ paper.publisherName || '老师' }} 发起 · {{ paper.questionCount }} 题 ·
              {{ paper.durationMinutes }} 分钟 · 合格线 {{ paper.passScore }} 分
            </p>
          </div>
          <el-button type="primary" @click="router.push('/training/practice')">去作答</el-button>
        </div>
      </section>

      <section v-if="student.rotation" class="stats">
        <article>
          <span>截止日期</span>
          <strong>{{ student.rotation.dueOn || '未设置' }}</strong>
        </article>
        <article>
          <span>合格要求</span>
          <strong>{{ student.rotation.passScore }} 分</strong>
        </article>
        <article>
          <span>完成进度</span>
          <strong>{{ student.rotation.done }} / {{ student.rotation.total }}</strong>
          <el-progress :percentage="student.rotation.progress" :stroke-width="8" />
        </article>
      </section>

      <section class="block">
        <h3>尚未完成</h3>
        <div v-if="!student.today.length" class="empty">
          {{
            student.tasks.some((item) => item.tier !== 'EXTENSION')
              ? '今日必做已完成。'
              : '老师还没有布置必做病例。'
          }}
        </div>
        <article v-for="task in student.today" :key="task.id" class="task">
          <div class="task-main">
            <div class="task-title">
              <el-tag size="small" :type="task.kind === 'CASE' ? 'primary' : 'success'" effect="plain">
                {{ task.kindText }}
              </el-tag>
              <strong>{{ task.title }}</strong>
              <el-tag v-if="task.overdue" size="small" type="danger">已逾期</el-tag>
              <el-tag v-else-if="task.dueToday" size="small" type="warning">今日到期</el-tag>
            </div>
            <p>{{ task.summary }}</p>
            <p class="meta">
              截止 {{ task.dueOn || '随轮转' }}
              <template v-if="task.kind === 'CASE'"> · 合格分 {{ task.passScore }}</template>
              <template v-if="task.score != null"> · 当前 {{ task.score }} 分</template>
              · {{ task.statusText }}
            </p>
          </div>
          <div class="task-actions">
            <el-button v-if="task.kind === 'CASE'" type="primary" @click="startCase(task)">学习这例</el-button>
            <template v-else>
              <el-button @click="openKnowledge(task)">去学习</el-button>
              <el-button v-if="!task.resourceId" type="primary" @click="markLearned(task)">标记已学</el-button>
            </template>
          </div>
        </article>
      </section>

      <section class="block">
        <h3>拓展病例</h3>
        <p class="lead">老师按你的年级或轮转组推荐的选做。做完不计入上面的必做进度。</p>
        <div v-if="!student.tasks.some((item) => item.tier === 'EXTENSION')" class="empty">
          还没有拓展病例。
        </div>
        <article
          v-for="task in student.tasks.filter((item) => item.tier === 'EXTENSION')"
          :key="task.id"
          class="task"
        >
          <div class="task-main">
            <div class="task-title">
              <el-tag size="small" type="warning" effect="plain">拓展病例</el-tag>
              <strong>{{ task.title }}</strong>
            </div>
            <p class="meta">{{ task.statusText }}<template v-if="task.score != null"> · {{ task.score }} 分</template></p>
          </div>
          <div class="task-actions">
            <el-button v-if="task.kind === 'CASE'" type="primary" @click="startCase(task)">学习这例</el-button>
          </div>
        </article>
      </section>

      <section class="block">
        <h3>本轮转全部必做</h3>
        <el-table :data="student.tasks.filter((item) => item.tier !== 'EXTENSION')" empty-text="还没有必做项">
          <el-table-column prop="kindText" label="类型" width="120" />
          <el-table-column prop="title" label="内容" min-width="220" />
          <el-table-column prop="dueOn" label="截止日期" width="140" />
          <el-table-column label="合格要求" width="120">
            <template #default="{ row }">
              {{ row.kind === 'CASE' ? `${row.passScore} 分` : '阅读完成' }}
            </template>
          </el-table-column>
          <el-table-column label="进度" width="140">
            <template #default="{ row }">
              <el-tag size="small" :type="statusType(row)" effect="plain">{{ row.statusText }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </template>

    <template v-else-if="teacher">
      <div class="teacher-board">
      <header class="page-head">
        <div>
          <h2>学员情况</h2>
          <p>先看全班概况，再按页签处理学情、布置和待批改。</p>
        </div>
        <el-button type="primary" @click="router.push('/training/class')">管理班级</el-button>
      </header>

      <section class="teacher-metrics" aria-label="全班核心指标">
        <article class="clickable-card" @click="openKpiModal('students')">
          <div class="tm-label">
            <span>学员数</span>
            <span class="tm-hint">&gt;</span>
          </div>
          <strong>{{ classSummary.students }}</strong>
          <span>已交卷 {{ classSummary.practiced }} 人</span>
        </article>
        <article class="clickable-card" @click="openKpiModal('practice')">
          <div class="tm-label">
            <span>练习次数</span>
            <span class="tm-hint">&gt;</span>
          </div>
          <strong>{{ classSummary.practice }}</strong>
          <span>全班交卷总人次</span>
        </article>
        <article class="clickable-card" @click="openKpiModal('avgScore')">
          <div class="tm-label">
            <span>平均分</span>
            <span class="tm-hint">&gt;</span>
          </div>
          <strong>{{ classSummary.avg.toFixed(1) }}</strong>
          <span>练习综合达标水平</span>
        </article>
        <article class="clickable-card" @click="openKpiModal('studyHours')">
          <div class="tm-label">
            <span>总学时</span>
            <el-tooltip
              content="学时记录学员在机练习实际操作时长，交卷即固化；教师通过/驳回判定阅片质量，不修改物理学时。"
              placement="top"
            >
              <el-icon class="tm-help"><question-filled /></el-icon>
            </el-tooltip>
            <span class="tm-hint">&gt;</span>
          </div>
          <strong>{{ formatMinutes(classSummary.seconds) }}</strong>
          <span>在机有效练习时长</span>
        </article>
      </section>

      <el-tabs v-model="activeTeacherTab" type="border-card" class="teacher-tabs" @tab-change="onTabChange">
        <el-tab-pane label="学情分析" name="monitor">
        <h3 class="subhead">按组查看</h3>
        <p class="lead">按年级、轮转批次和带教组分别看完成情况和常见漏诊、误诊。还没填写的学员先算在「未分组」。</p>
        <div class="assign">
          <el-select v-model="yearFilter" clearable placeholder="全部年级" style="width: 160px" @change="onDropdownFilterChange" @clear="onDropdownFilterChange">
            <el-option v-for="item in yearOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select v-model="batchFilter" clearable placeholder="全部轮转批次" style="width: 180px" @change="onDropdownFilterChange" @clear="onDropdownFilterChange">
            <el-option v-for="item in batchOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-select v-model="mentorFilter" clearable placeholder="全部带教组" style="width: 160px" @change="onDropdownFilterChange" @clear="onDropdownFilterChange">
            <el-option v-for="item in mentorOptions" :key="item" :label="item" :value="item" />
          </el-select>
          <el-button v-if="isAnyFilterActive" size="small" :icon="RefreshLeft" @click="clearAllGroupFilters(true)">
            重置筛选
          </el-button>
        </div>
        <div class="group-grid">
          <article
            v-for="group in visibleGroups"
            :key="`${group.studyYear}-${group.rotationBatch}-${group.mentorGroup}`"
            class="clickable-group-card"
            :class="{ 'is-selected': isGroupSelected(group) }"
            @click="filterByGroup(group)"
          >
            <div class="group-card-header">
              <strong>{{ group.studyYear }} · {{ group.rotationBatch }} · {{ group.mentorGroup }}</strong>
              <span v-if="isGroupSelected(group)" class="group-filter-tip is-active">
                <el-icon><Check /></el-icon> 已筛选（点击取消）
              </span>
              <span v-else class="group-filter-tip">点击快速筛选</span>
            </div>
            <p>{{ group.studentCount }} 名学员，完成 {{ group.done }} / {{ group.total }} 项，进度 {{ group.progress }}%。</p>
            <div v-if="group.weakLabels && group.weakLabels.length" class="weak-tag-group">
              <span class="weak-title">常见问题：</span>
              <template v-for="w in group.weakLabels" :key="w.label">
                <el-tag
                  v-if="w.missed > 0"
                  size="small"
                  type="danger"
                  class="clickable-weak-tag"
                  @click.stop="openGroupWeak(group, w.label, 'missed')"
                >
                  漏诊{{ w.label }} {{ w.missed }}次 &gt;
                </el-tag>
                <el-tag
                  v-if="w.falsePositive > 0"
                  size="small"
                  type="warning"
                  class="clickable-weak-tag"
                  @click.stop="openGroupWeak(group, w.label, 'false_positive')"
                >
                  误诊{{ w.label }} {{ w.falsePositive }}次 &gt;
                </el-tag>
              </template>
            </div>
            <p v-else class="empty-weak-tip">这一组还没有汇总出漏诊或误诊。</p>
          </article>
        </div>

        <!-- 层级面包屑导航 -->
        <div class="drilldown-breadcrumb-bar">
          <span class="bc-lead">层级路径：</span>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>
              <a
                href="javascript:void(0)"
                class="bc-link"
                :class="{ 'bc-active-link': isAnyFilterActive }"
                @click="clearAllGroupFilters(true)"
              >
                全部学员
              </a>
            </el-breadcrumb-item>
            <el-breadcrumb-item v-if="yearFilter">
              <a
                href="javascript:void(0)"
                class="bc-link"
                :class="{ 'bc-active-link': batchFilter || mentorFilter }"
                @click="selectBreadcrumbYear"
              >
                {{ yearFilter }}
              </a>
            </el-breadcrumb-item>
            <el-breadcrumb-item v-if="batchFilter">
              <a
                href="javascript:void(0)"
                class="bc-link"
                :class="{ 'bc-active-link': mentorFilter }"
                @click="selectBreadcrumbBatch"
              >
                {{ batchFilter }}
              </a>
            </el-breadcrumb-item>
            <el-breadcrumb-item v-if="mentorFilter">
              <span class="bc-current">{{ mentorFilter }}</span>
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <!-- 常驻高可见筛选状态提示条 -->
        <div v-if="isAnyFilterActive" class="filter-status-banner">
          <div class="fsb-left">
            <el-icon class="fsb-icon"><Filter /></el-icon>
            <span class="fsb-title">已按带教维度筛选：</span>
            <el-tag v-if="yearFilter" size="small" closable @close="clearFilter('year')">
              年级：{{ yearFilter }}
            </el-tag>
            <el-tag v-if="batchFilter" size="small" closable @close="clearFilter('batch')">
              批次：{{ batchFilter }}
            </el-tag>
            <el-tag v-if="mentorFilter" size="small" type="success" closable @close="clearFilter('mentor')">
              带教组：{{ mentorFilter }}
            </el-tag>
            <span class="fsb-count">
              （已匹配 <strong>{{ filteredStudents.length }}</strong> 名学员 / 全班共 {{ teacher?.students?.length || 0 }} 人）
            </span>
          </div>
          <div class="fsb-actions">
            <el-button type="primary" size="small" :icon="Back" @click="clearAllGroupFilters(true)">
              返回全部学员
            </el-button>
            <el-button size="small" :icon="RefreshLeft" @click="clearAllGroupFilters(true)">
              清除筛选
            </el-button>
            <el-tooltip content="清除筛选，返回全部学员" placement="top">
              <button class="fsb-close-circle" type="button" @click="clearAllGroupFilters(true)" aria-label="清除筛选">
                <el-icon><Close /></el-icon>
              </button>
            </el-tooltip>
          </div>
        </div>

        <h3 class="subhead">学员进度</h3>
        <el-table :data="filteredStudents" empty-text="这一组还没有学员">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="expand-tasks-wrap">
                <div v-for="item in row.tasks || []" :key="item.taskId" class="snap-row">
                  <span class="snap-title">{{ taskTitle(item.taskId) }}</span>
                  <el-tag size="small" :type="statusType(item)" effect="plain">{{ item.statusText }}</el-tag>
                  <span v-if="item.score != null" class="snap-score">{{ item.score }} 分</span>
                  <el-button
                    v-if="item.sessionId && item.caseId"
                    link
                    type="primary"
                    size="small"
                    class="snap-btn"
                    @click="openTaskWorkstation(item)"
                  >
                    查看判读报告 &gt;
                  </el-button>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="学员" min-width="120" />
          <el-table-column prop="studyYear" label="年级" width="110" />
          <el-table-column prop="rotationBatch" label="轮转批次" width="130" />
          <el-table-column prop="mentorGroup" label="带教组" width="120" />
          <el-table-column label="分组修改人" min-width="180">
            <template #default="{ row }">
              {{ actorLabel(row.groupEditorName, row.groupEditorRole) || '尚未记录' }}
            </template>
          </el-table-column>
          <el-table-column label="练习次数" width="100">
            <template #default="{ row }">{{ row.practiceCount }}</template>
          </el-table-column>
          <el-table-column label="完成病例" width="100">
            <template #default="{ row }">{{ row.completedCases }}</template>
          </el-table-column>
          <el-table-column label="平均成绩" width="100">
            <template #default="{ row }">{{ row.avgScore.toFixed(1) }}</template>
          </el-table-column>
          <el-table-column label="学时" width="120">
            <template #default="{ row }">{{ formatMinutes(row.studySeconds) }}</template>
          </el-table-column>
          <el-table-column label="必做" width="120">
            <template #default="{ row }">{{ row.done }} / {{ row.total }}</template>
          </el-table-column>
          <el-table-column label="进度" min-width="200">
            <template #default="{ row }">
              <el-progress :percentage="row.progress" :stroke-width="8" />
            </template>
          </el-table-column>
          <el-table-column label="" width="120">
            <template #default="{ row }">
              <el-button link type="primary" @click="openStudent(row)">查看学情</el-button>
            </template>
          </el-table-column>
        </el-table>
        </el-tab-pane>

        <el-tab-pane label="任务与病例布置" name="assign">
      <h3 class="subhead">轮转要求</h3>
      <section v-if="teacher.rotation" class="stats">
        <article>
          <span>轮转</span>
          <el-input v-model="titleDraft" />
        </article>
        <article>
          <span>截止日期</span>
          <el-date-picker v-model="dueDraft" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" />
        </article>
        <article>
          <span>合格要求</span>
          <el-input-number v-model="passDraft" :min="0" :max="100" />
          <el-button type="primary" @click="saveRotation">保存</el-button>
        </article>
      </section>

      <section class="block">
        <h3>推荐病例</h3>
        <p class="lead">必做计入该年级或轮转组的完成进度。拓展是选做。同一例可以分别推荐给不同范围。</p>
        <div class="assign case-filters">
          <el-select v-model="caseCategoryFilter" clearable placeholder="病种" style="width: 160px">
            <el-option v-for="item in CATEGORY_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select v-model="caseDifficultyFilter" clearable placeholder="难度" style="width: 110px">
            <el-option v-for="item in DIFFICULTY_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select v-model="caseGradeFilter" clearable placeholder="DR 分级" style="width: 110px">
            <el-option v-for="g in DR_GRADE_CHOICES" :key="g" :label="`${g} 级`" :value="g" />
          </el-select>
          <el-button link type="primary" @click="goCaseLibrary">找不到？去上传 / 管理病例</el-button>
        </div>
        <el-alert
          v-if="pendingCases.length"
          type="warning"
          :closable="false"
          show-icon
          class="case-pending-tip"
        >
          <template #title>
            你还有 {{ pendingCases.length }} 例病例未开放练习，暂时不能推荐。
            <el-button link type="primary" @click="goCaseLibrary">去病例库处理</el-button>
          </template>
        </el-alert>
        <div v-if="optionsLoaded && !caseOptions.length" class="case-empty">
          <span>暂无可选病例，请先上传病例，发布并开放练习。</span>
          <el-button size="small" type="primary" @click="goCaseLibrary">去病例库</el-button>
        </div>
        <div class="assign">
          <el-select
            v-model="caseId"
            clearable
            filterable
            placeholder="选择病例"
            :no-data-text="caseFiltersActive ? '没有符合筛选条件的病例' : '暂无可选病例'"
            :no-match-text="'没有匹配的病例'"
            style="width: 320px"
          >
            <el-option-group v-if="filteredCaseOptions.length" label="可推荐">
              <el-option v-for="item in filteredCaseOptions" :key="item.id" :label="item.label" :value="item.id" />
            </el-option-group>
            <el-option-group v-if="filteredPendingCases.length" label="我的待处理病例（不可选）">
              <el-option
                v-for="item in filteredPendingCases"
                :key="`pending-${item.id}`"
                :label="item.label"
                :value="-item.id"
                disabled
              >
                <span class="pending-option">
                  <span class="pending-label">{{ item.label }}</span>
                  <span class="pending-step">{{ item.missingStep }}</span>
                </span>
              </el-option>
            </el-option-group>
          </el-select>
          <el-select v-model="caseTier" style="width: 120px">
            <el-option label="必做病例" value="REQUIRED" />
            <el-option label="拓展病例" value="EXTENSION" />
          </el-select>
          <el-select v-model="caseScope" style="width: 140px" @change="caseScopeValue = ''">
            <el-option label="全部学员" value="ALL" />
            <el-option label="按年级" value="YEAR" />
            <el-option label="按轮转组" value="GROUP" />
          </el-select>
          <el-select
            v-if="caseScope !== 'ALL'"
            v-model="caseScopeValue"
            filterable
            :placeholder="caseScope === 'YEAR' ? '选择年级' : '选择轮转组'"
            style="width: 180px"
          >
            <el-option v-for="item in assignTargets" :key="item" :label="item" :value="item" />
          </el-select>
          <el-button type="primary" @click="addCase">标记推荐</el-button>
        </div>
        <div class="assign">
          <el-select v-model="resourceId" clearable filterable placeholder="选择已发布资料" style="width: 320px">
            <el-option v-for="item in resourceOptions" :key="item.id" :label="item.label" :value="item.id" />
          </el-select>
          <el-input v-model="knowledgeTitle" placeholder="或直接写知识点标题" style="width: 280px" />
          <el-button type="primary" @click="addKnowledge">加入知识点</el-button>
        </div>
      </section>

      <section class="block">
        <h3>本轮转任务</h3>
        <p v-if="teacher.rotation" class="lead">
          必做完成 {{ teacher.rotation.done }} / {{ teacher.rotation.total }} 项，
          进度 {{ teacher.rotation.progress }}%。顺序就是学员看到的顺序。
        </p>
        <el-button @click="arrangeBySpectrum">按病谱排列</el-button>
        <el-table
          class="task-order-table"
          :data="teacher.tasks"
          row-key="id"
          :row-class-name="taskRowClass"
          empty-text="还没有布置"
        >
          <el-table-column label="顺序" width="72" align="center">
            <template #default="{ $index }">
              <div class="order-arrows">
                <button
                  type="button"
                  class="order-arrow"
                  title="上移"
                  aria-label="上移"
                  :disabled="$index === 0"
                  @click="moveTask($index, -1)"
                >
                  <el-icon><ArrowUp /></el-icon>
                </button>
                <button
                  type="button"
                  class="order-arrow"
                  title="下移"
                  aria-label="下移"
                  :disabled="$index === teacher.tasks.length - 1"
                  @click="moveTask($index, 1)"
                >
                  <el-icon><ArrowDown /></el-icon>
                </button>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="kindText" label="类型" width="120" />
          <el-table-column prop="scopeText" label="对象" width="140" />
          <el-table-column prop="title" label="内容" min-width="240" />
          <el-table-column prop="dueOn" label="截止日期" width="140" />
          <el-table-column label="合格要求" width="120">
            <template #default="{ row }">
              {{ row.kind === 'CASE' ? `${row.passScore} 分` : '阅读完成' }}
            </template>
          </el-table-column>
          <el-table-column prop="statusText" label="完成人数" width="140" />
          <el-table-column label="" width="160">
            <template #default="{ row }">
              <el-button
                v-if="row.kind === 'CASE' ? row.caseNo : row.resourceId"
                link
                type="primary"
                @click="openAssigned(row)"
              >
                打开
              </el-button>
              <el-button link type="danger" @click="removeTask(row)">撤下</el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
        </el-tab-pane>

      </el-tabs>
      <p class="review-guide">
        当前有 {{ pendingReviewCount }} 份作业待评定。
        <el-button link type="primary" @click="router.push('/training/reading?tab=review')">
          去作业批阅
        </el-button>
      </p>

      <!-- 学员学情抽屉（四层下钻第3层） -->
      <StudentDrilldownDrawer
        v-model="drawerOpen"
        :student="focusStudent"
        @group-updated="onGroupUpdated"
      />

      <!-- 全局/班级核心指标穿透弹窗（四层下钻第1层） -->
      <KpiDrilldownDialog
        v-model="kpiModalVisible"
        :kpi-type="kpiModalType"
        :title="kpiModalTitle"
        :students="teacher?.students || []"
        @select-student="onSelectStudentFromKpi"
      />

      <!-- 常见漏诊误诊病例/题目明细弹窗（四层下钻第4层） -->
      <WeakCaseListDialog
        v-model="weakModalVisible"
        :title="weakModalTitle"
        :label="weakModalLabel"
        :error-type="weakModalType"
        :study-year="weakModalGroup?.studyYear"
        :rotation-batch="weakModalGroup?.rotationBatch"
        :mentor-group="weakModalGroup?.mentorGroup"
      />
      </div>
    </template>
  </div>
</template>

<style scoped>
.home-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 28px 32px 48px;
  color: var(--hy-c-text, #1d2129);
}
.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.page-head h2 {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 650;
}
.page-head p,
.lead,
.task p,
.meta {
  margin: 0;
  color: var(--hy-c-text-2, #4e5969);
  font-size: 14px;
  line-height: 1.6;
}
.stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
  margin: 20px 0 8px;
}
.stats article {
  background: var(--hy-c-surface, #fff);
  border: 1px solid var(--hy-c-border, #e5e6eb);
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.stats span {
  color: var(--hy-c-text-2, #4e5969);
  font-size: 13px;
}
.stats strong {
  font-size: 22px;
  color: var(--hy-c-text, #1d2129);
}
.block {
  margin-top: 28px;
}
.block h3 {
  margin: 0 0 12px;
  font-size: 16px;
}
.exam-callout {
  background: var(--hy-c-surface, #fff);
  border: 1px solid var(--hy-c-border-strong, #dfe3ea);
  border-radius: 12px;
  padding: 16px 18px 8px;
}
.exam-call {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  padding: 8px 0 14px;
}
.exam-call p {
  margin: 4px 0 0;
  color: var(--hy-c-text-2, #4e5969);
  font-size: 13px;
}
.students-entry {
  margin-top: 20px;
  background: var(--hy-c-fill, #f7f8fa);
  border: 1px solid var(--hy-c-border, #e5e6eb);
  border-radius: 12px;
  padding: 18px 18px 8px;
}
.subhead {
  margin-top: 22px;
}
.class-stats {
  margin-top: 12px;
}
.task {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  margin-bottom: 12px;
  background: var(--hy-c-surface, #fff);
  border: 1px solid var(--hy-c-border, #e5e6eb);
  border-radius: 12px;
}
.task-title {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.task-title strong {
  color: var(--hy-c-text, #1d2129);
}
.task-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.assign {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.case-filters {
  align-items: center;
}
.case-pending-tip {
  margin-bottom: 10px;
}
.case-empty {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.pending-option {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}
.pending-label {
  overflow: hidden;
  text-overflow: ellipsis;
}
.pending-step {
  flex-shrink: 0;
  color: var(--el-color-warning);
  font-size: 12px;
}
.empty {
  padding: 28px 0;
  color: var(--hy-c-text-2, #4e5969);
}
.snap {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px;
  color: var(--hy-c-text, #1d2129);
}
.detail-stats {
  margin-top: 0;
}
.detail-stats strong {
  font-size: 18px;
}
.comment-line {
  display: flex;
  gap: 8px;
  align-items: center;
}
.group-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}
.group-grid article {
  background: var(--hy-c-fill, #f7f9fb);
  border: 1px solid var(--hy-c-border-strong, #d5dee8);
  border-radius: 12px;
  padding: 14px 16px;
}
.group-grid strong {
  color: var(--hy-c-text, #1d2129);
}
.group-grid p {
  margin: 6px 0 0;
  color: var(--hy-c-text-2, #4e5969);
  font-size: 13px;
  line-height: 1.5;
}
.teacher-board {
  background: var(--hy-c-fill, #eef2f6);
  border: 1px solid var(--hy-c-border-strong, #d5dee8);
  border-radius: 16px;
  padding: 20px 22px 24px;
}
.teacher-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin: 16px 0 18px;
}
.teacher-metrics article {
  background: var(--hy-c-fill, #f7f9fb);
  border: 1px solid var(--hy-c-border-strong, #d5dee8);
  border-radius: 12px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.clickable-card {
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.clickable-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border-color: #165dff !important;
}
.tm-hint {
  font-size: 13px;
  color: #8f959e;
  font-weight: normal;
}
.clickable-group-card {
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.clickable-group-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border-color: #165dff !important;
}
.clickable-group-card.is-selected {
  border-color: #165dff !important;
  background-color: #f2f7ff !important;
  box-shadow: 0 0 0 2px rgba(22, 93, 255, 0.25) !important;
}
.group-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.group-filter-tip {
  font-size: 12px;
  color: #165dff;
}
.group-filter-tip.is-active {
  color: #165dff;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.drilldown-breadcrumb-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  margin-bottom: 12px;
  padding: 8px 12px;
  background: #f7f8fa;
  border-radius: 6px;
  border: 1px solid #e5e6eb;
}
.bc-lead {
  font-size: 13px;
  color: #4e5969;
  font-weight: 500;
}
.bc-link {
  color: #4e5969;
  text-decoration: none;
  font-size: 13px;
  transition: color 0.15s ease;
}
.bc-active-link {
  color: #165dff !important;
  font-weight: 500;
  cursor: pointer;
}
.bc-active-link:hover {
  text-decoration: underline;
}
.bc-current {
  color: #1d2129;
  font-weight: 600;
  font-size: 13px;
}
.filter-status-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  background: #e8f3ff;
  border: 1px solid #b7d6ff;
  border-radius: 6px;
  padding: 10px 16px;
  margin-bottom: 16px;
}
.fsb-left {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}
.fsb-icon {
  font-size: 16px;
  color: #165dff;
}
.fsb-title {
  font-size: 13px;
  font-weight: 600;
  color: #1d2129;
}
.fsb-count {
  font-size: 12px;
  color: #4e5969;
  margin-left: 4px;
}
.fsb-count strong {
  color: #165dff;
}
.fsb-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
.fsb-close-circle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: none;
  background: rgba(0, 0, 0, 0.05);
  color: #4e5969;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.18s ease;
}
.fsb-close-circle:hover {
  background: rgba(0, 0, 0, 0.12);
  color: #1d2129;
}
.weak-tag-group {
  margin-top: 8px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.weak-title {
  font-size: 12px;
  color: #646a73;
}
.clickable-weak-tag {
  cursor: pointer;
  transition: opacity 0.15s ease;
}
.clickable-weak-tag:hover {
  opacity: 0.82;
}
.empty-weak-tip {
  color: #8f959e !important;
  font-size: 12px !important;
}
.expand-tasks-wrap {
  padding: 8px 16px;
  background: #f7f8fa;
  border-radius: 8px;
}
.snap-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 6px 0;
  border-bottom: 1px dashed #e5e6eb;
}
.snap-row:last-child {
  border-bottom: none;
}
.snap-title {
  font-size: 13px;
  color: #1f2329;
  font-weight: 500;
}
.snap-score {
  font-size: 13px;
  color: #165dff;
  font-weight: 600;
}
.snap-btn {
  margin-left: auto;
}
.teacher-metrics span {
  color: var(--hy-c-text-2, #4e5969);
  font-size: 13px;
}
.teacher-metrics strong {
  font-size: 22px;
  color: var(--hy-c-text, #1d2129);
}
.tm-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.tm-help {
  color: var(--hy-c-text-3, #9aa1af);
  cursor: pointer;
  font-size: 13px;
  transition: color 0.15s ease;
}
.tm-help:hover {
  color: #409eff;
}
.review-guide {
  margin: 0 0 12px;
  padding: 10px 14px;
  background: var(--hy-c-fill, #f7f9fb);
  border: 1px solid var(--hy-c-border-strong, #dfe3ea);
  border-radius: 8px;
  color: var(--hy-c-text, #1d2129);
  font-size: 14px;
  line-height: 1.6;
}
.teacher-board :deep(.el-tabs--border-card) {
  background: var(--hy-c-fill, #eef2f6);
  border-color: var(--hy-c-border-strong, #d5dee8);
  box-shadow: none;
}
.teacher-board :deep(.el-tabs--border-card > .el-tabs__header) {
  background: #e4eaf1;
  border-bottom-color: var(--hy-c-border-strong, #d5dee8);
}
.teacher-board :deep(.el-tabs--border-card > .el-tabs__content) {
  background: var(--hy-c-fill, #eef2f6);
}
.teacher-board :deep(.el-table),
.teacher-board :deep(.el-table tr),
.teacher-board :deep(.el-table th.el-table__cell),
.teacher-board :deep(.el-table td.el-table__cell) {
  background: var(--hy-c-fill, #f7f9fb);
}
.order-arrows {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}
.order-arrow {
  width: 26px;
  height: 18px;
  padding: 0;
  border: 1px solid var(--hy-c-border-strong, #c9cdd4);
  border-radius: 4px;
  background: var(--hy-c-surface, #ffffff);
  color: var(--hy-c-text, #1d2129);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
}
.order-arrow:hover:not(:disabled) {
  color: #1677ff;
  border-color: #1677ff;
  background: var(--hy-c-primary-soft, #f0f6ff);
}
.order-arrow:disabled {
  color: var(--hy-c-text-4, #c9cdd4);
  background: var(--hy-c-fill, #f2f3f5);
  cursor: not-allowed;
}
.teacher-board :deep(.task-order-table tr.is-just-moved td.el-table__cell) {
  background: var(--hy-c-primary-soft, #d6e8ff) !important;
  box-shadow: inset 4px 0 0 #1677ff;
  animation: task-row-flash 0.45s ease;
}
@keyframes task-row-flash {
  0% { background: #7eb6ff; }
  100% { background: var(--hy-c-primary-soft, #d6e8ff); }
}
@media (max-width: 800px) {
  .teacher-metrics {
    grid-template-columns: 1fr 1fr;
  }
  .stats {
    grid-template-columns: 1fr;
  }
  .task {
    flex-direction: column;
  }
}
</style>

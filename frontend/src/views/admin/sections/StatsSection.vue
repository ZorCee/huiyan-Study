<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Refresh,
  Search,
  DataAnalysis,
  User,
  Document,
  Trophy,
  Back,
  Close,
  RefreshLeft,
  Check,
  Filter
} from '@element-plus/icons-vue'
import { CommonApi, RotationApi } from '@/api'
import type { TeacherHome, GroupSummary } from '@/api/rotation'
import StudentDrilldownDrawer from '@/views/training/components/StudentDrilldownDrawer.vue'
import WeakCaseListDialog from '@/views/training/components/WeakCaseListDialog.vue'
import KpiDrilldownDialog from '@/views/training/components/KpiDrilldownDialog.vue'

type TrainingOverview = CommonApi.TrainingOverview
type StudyHoursItem = CommonApi.StudyHoursItem

const props = defineProps<{
  /** TEACHER/ADMIN 才可查看 */
  canManage: boolean
}>()

const router = useRouter()
const route = useRoute()

/* ========== 全院培训统计 ========== */

const overview = ref<TrainingOverview | null>(null)
const overviewLoading = ref(false)

const fetchOverview = async () => {
  if (!props.canManage) return
  overviewLoading.value = true
  try {
    overview.value = await CommonApi.getTrainingOverview()
  } catch {
    overview.value = null
  } finally {
    overviewLoading.value = false
  }
}

const passRatePercent = computed(() => {
  const r = overview.value?.passRate || 0
  return Math.round(r * 1000) / 10
})
const avgIouPercent = computed(() => {
  const r = overview.value?.avgIou || 0
  return Math.round(r * 1000) / 10
})

const maxByDifficulty = computed(() => {
  const arr = overview.value?.byDifficulty || []
  return arr.reduce((m, it) => Math.max(m, it.value), 1)
})
const maxByDrGrade = computed(() => {
  const arr = overview.value?.byDrGrade || []
  return arr.reduce((m, it) => Math.max(m, it.value), 1)
})

/* ========== 学员学时汇总 ========== */

const studyList = ref<StudyHoursItem[]>([])
const studyTotal = ref(0)
const studyLoading = ref(false)
const studyFilter = reactive({ keyword: '' })
const studyPagination = reactive({ page: 1, pageSize: 50 })

const fetchStudy = async () => {
  if (!props.canManage) return
  studyLoading.value = true
  try {
    const res = await CommonApi.getStudyHours({
      keyword: studyFilter.keyword || undefined,
      page: studyPagination.page,
      pageSize: studyPagination.pageSize
    })
    studyList.value = res?.list || []
    studyTotal.value = res?.total || 0
  } catch {
    studyList.value = []
    studyTotal.value = 0
  } finally {
    studyLoading.value = false
  }
}

const onStudyFilter = () => {
  studyPagination.page = 1
  fetchStudy()
}

const clearStudyFilter = () => {
  studyFilter.keyword = ''
  onStudyFilter()
}

/* ========== 带教组与学情下钻数据 ========== */

const rotationHome = ref<TeacherHome | null>(null)

const fetchRotation = async () => {
  if (!props.canManage) return
  try {
    const res = await RotationApi.getHome()
    if (res.role === 'teacher') {
      rotationHome.value = res
    }
  } catch {
    rotationHome.value = null
  }
}

/* ========== 下钻弹窗与抽屉状态 ========== */

const kpiModalVisible = ref(false)
const kpiModalType = ref<'students' | 'practice' | 'avgScore' | 'studyHours' | 'cases' | 'passRate'>('students')
const kpiModalTitle = ref('')

const openKpiModal = (type: 'students' | 'practice' | 'avgScore' | 'studyHours' | 'cases' | 'passRate') => {
  kpiModalType.value = type
  if (type === 'students') kpiModalTitle.value = '全院参训学员名单及学情明细'
  else if (type === 'cases') kpiModalTitle.value = '全院病例难度与分级分布明细'
  else if (type === 'practice') kpiModalTitle.value = '全院答卷与交卷记录明细'
  else if (type === 'passRate') kpiModalTitle.value = '合格率与 IoU 重合度详情'
  kpiModalVisible.value = true
}

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

const selectedStudent = ref<any>(null)
const studentDrawerOpen = ref(false)

const openStudentDrilldown = (row: StudyHoursItem) => {
  const hit = rotationHome.value?.students?.find((s) => s.userId === row.userId)
  selectedStudent.value = hit || {
    userId: row.userId,
    name: row.realName || row.username,
    username: row.username,
    department: row.department
  }
  studentDrawerOpen.value = true
}

const onSelectStudentFromKpi = (stu: any) => {
  kpiModalVisible.value = false
  selectedStudent.value = stu
  studentDrawerOpen.value = true
}

const onGroupUpdated = () => {
  fetchRotation()
  fetchStudy()
}

const selectedMentorGroup = ref('')

const isGroupSelected = (group: GroupSummary) => {
  return selectedMentorGroup.value === group.mentorGroup
}

const syncToQuery = (replace = false) => {
  const q = { ...route.query }
  if (selectedMentorGroup.value) {
    q.studyGroup = selectedMentorGroup.value
  } else {
    delete q.studyGroup
  }
  if (replace) {
    router.replace({ query: q })
  } else {
    router.push({ query: q })
  }
}

const syncFromQuery = () => {
  const qGroup = typeof route.query.studyGroup === 'string' ? route.query.studyGroup : ''
  if (qGroup !== selectedMentorGroup.value) {
    selectedMentorGroup.value = qGroup
    studyFilter.keyword = qGroup === '未分组' ? '' : qGroup
    onStudyFilter()
  }
}

watch(
  () => route.query.studyGroup,
  () => {
    syncFromQuery()
  }
)

const filterStudyByGroup = (group: GroupSummary) => {
  if (isGroupSelected(group)) {
    // 二次点击取消筛选
    clearAdminGroupFilter(true)
    ElMessage.info('已取消带教组筛选，展示全院学员')
    return
  }

  selectedMentorGroup.value = group.mentorGroup
  studyFilter.keyword = group.mentorGroup === '未分组' ? '' : group.mentorGroup
  onStudyFilter()
  syncToQuery(false)
  ElMessage.success(`已筛选【${group.mentorGroup || '带教组'}】学员学时列表`)
}

const clearAdminGroupFilter = (pushHistory = true) => {
  selectedMentorGroup.value = ''
  studyFilter.keyword = ''
  onStudyFilter()
  if (pushHistory) {
    syncToQuery(false)
  }
}

const goToCaseLibraryWithFilter = (field?: string, val?: string) => {
  router.push({
    path: '/training/cases',
    query: field && val ? { [field]: val } : undefined
  })
}

const refresh = () => {
  fetchOverview()
  fetchStudy()
  fetchRotation()
}

onMounted(() => {
  refresh()
  syncFromQuery()
})
</script>

<template>
  <div class="stats-section">
    <div v-if="!canManage" class="card">
      <el-alert
        title="当前账号无统计报表查看权限"
        type="warning"
        description="仅带教医师（TEACHER）和平台管理员（ADMIN）可查看统计报表。"
        :closable="false"
        show-icon
      />
    </div>

    <template v-else>
      <!-- 总览数字卡（可下钻） -->
      <div class="overview-grid" v-loading="overviewLoading">
        <div class="ov-card clickable-ov-card" @click="openKpiModal('students')">
          <div class="ov-icon"><el-icon><User /></el-icon></div>
          <div class="ov-info">
            <div class="ov-num">{{ overview?.totalUsers || 0 }}</div>
            <div class="ov-label">参训学员 <span class="ov-drill">&gt;</span></div>
          </div>
        </div>
        <div class="ov-card clickable-ov-card" @click="openKpiModal('cases')">
          <div class="ov-icon"><el-icon><Document /></el-icon></div>
          <div class="ov-info">
            <div class="ov-num">{{ overview?.totalCases || 0 }}</div>
            <div class="ov-label">病例总数 <span class="ov-drill">&gt;</span></div>
          </div>
        </div>
        <div class="ov-card clickable-ov-card" @click="openKpiModal('practice')">
          <div class="ov-icon"><el-icon><DataAnalysis /></el-icon></div>
          <div class="ov-info">
            <div class="ov-num">{{ overview?.totalRecords || 0 }}</div>
            <div class="ov-label">答卷总数 <span class="ov-drill">&gt;</span></div>
          </div>
        </div>
        <div class="ov-card clickable-ov-card" @click="openKpiModal('passRate')">
          <div class="ov-icon green"><el-icon><Trophy /></el-icon></div>
          <div class="ov-info">
            <div class="ov-num green-text">{{ avgIouPercent }}%</div>
            <div class="ov-label">平均 IoU <span class="ov-drill">&gt;</span></div>
          </div>
        </div>
        <div class="ov-card clickable-ov-card" @click="openKpiModal('passRate')">
          <div class="ov-icon blue"><el-icon><Trophy /></el-icon></div>
          <div class="ov-info">
            <div class="ov-num blue-text">{{ passRatePercent }}%</div>
            <div class="ov-label">合格率（IoU ≥ 0.6） <span class="ov-drill">&gt;</span></div>
          </div>
        </div>
        <div class="ov-card refresh-card" @click="fetchOverview">
          <div class="ov-icon"><el-icon><Refresh /></el-icon></div>
          <div class="ov-info">
            <div class="ov-num small">点击刷新</div>
            <div class="ov-label">重新拉取统计</div>
          </div>
        </div>
      </div>

      <!-- 分布图表（柱状，支持点击跳转病例库筛选） -->
      <div class="distrib-grid" v-loading="overviewLoading">
        <div class="card">
          <div class="card-header">
            <div class="card-title">病例难度分布</div>
            <span class="muted font12">{{ overview?.byDifficulty?.length || 0 }} 类 · 点击可前往病例库</span>
          </div>
          <div class="bar-list">
            <div
              v-for="it in overview?.byDifficulty || []"
              :key="it.label"
              class="bar-row clickable-bar"
              @click="goToCaseLibraryWithFilter('difficulty', it.label)"
            >
              <span class="bar-label">{{ it.label }}</span>
              <div class="bar-track">
                <div
                  class="bar-fill diff"
                  :style="{ width: ((it.value / maxByDifficulty) * 100).toFixed(1) + '%' }"
                ></div>
              </div>
              <span class="bar-value">{{ it.value }} &gt;</span>
            </div>
            <div v-if="!(overview?.byDifficulty?.length)" class="empty">暂无分布数据</div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <div class="card-title">DR 分级分布</div>
            <span class="muted font12">{{ overview?.byDrGrade?.length || 0 }} 级 · 点击可前往病例库</span>
          </div>
          <div class="bar-list">
            <div
              v-for="it in overview?.byDrGrade || []"
              :key="it.label"
              class="bar-row clickable-bar"
              @click="goToCaseLibraryWithFilter('goldDrGrade', it.label)"
            >
              <span class="bar-label">{{ it.label }}</span>
              <div class="bar-track">
                <div
                  class="bar-fill dr"
                  :style="{ width: ((it.value / maxByDrGrade) * 100).toFixed(1) + '%' }"
                ></div>
              </div>
              <span class="bar-value">{{ it.value }} &gt;</span>
            </div>
            <div v-if="!(overview?.byDrGrade?.length)" class="empty">暂无分布数据</div>
          </div>
        </div>
      </div>

      <!-- 带教组学情与常见漏诊误诊穿透（四层下钻第2层） -->
      <div v-if="rotationHome?.groups?.length" class="card">
        <div class="card-header">
          <div class="card-title">带教组学情与常见漏诊误诊穿透</div>
          <span class="muted font12">共 {{ rotationHome.groups.length }} 个带教组，点击组卡片或漏诊误诊数字可向下穿透</span>
        </div>
        <div class="admin-group-grid">
          <div
            v-for="group in rotationHome.groups"
            :key="`${group.studyYear}-${group.rotationBatch}-${group.mentorGroup}`"
            class="admin-group-card"
            :class="{ 'is-selected': isGroupSelected(group) }"
            @click="filterStudyByGroup(group)"
          >
            <div class="group-head">
              <strong>{{ group.studyYear }} · {{ group.rotationBatch }} · {{ group.mentorGroup }}</strong>
              <span v-if="isGroupSelected(group)" class="filter-link is-active">
                <el-icon><Check /></el-icon> 已筛选（点击取消）
              </span>
              <span v-else class="filter-link">筛选学员</span>
            </div>
            <p class="group-info">
              {{ group.studentCount }} 名学员，完成 {{ group.done }} / {{ group.total }} 项，
              进度 {{ group.progress }}%。
            </p>
            <div v-if="group.weakLabels && group.weakLabels.length" class="weak-tags">
              <span class="weak-lbl">常见薄弱点：</span>
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
            <p v-else class="muted font12 mt6">该组暂无漏诊或误诊汇总。</p>
          </div>
        </div>
      </div>

      <!-- 学员学时汇总（四层下钻第3层，点击行展开学情） -->
      <div class="card">
        <div class="card-header">
          <div class="card-title">
            学员学时汇总
            <span class="muted ml8">共 {{ studyTotal }} 人 · 点击学员行可查看学情明细与答卷复盘</span>
          </div>
          <div class="card-actions">
            <el-input
              v-model="studyFilter.keyword"
              placeholder="搜索用户名 / 姓名 / 带教组"
              :prefix-icon="Search"
              clearable
              size="small"
              style="width: 240px"
              @change="onStudyFilter"
              @clear="clearAdminGroupFilter(true)"
            />
            <el-button size="small" @click="clearAdminGroupFilter(true)">清除</el-button>
            <el-button :icon="Refresh" size="small" @click="fetchStudy">刷新</el-button>
          </div>
        </div>

        <!-- 层级面包屑导航 -->
        <div class="drilldown-breadcrumb-bar">
          <span class="bc-lead">当前层级：</span>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>
              <a
                href="javascript:void(0)"
                class="bc-link"
                :class="{ 'bc-active-link': !!(selectedMentorGroup || studyFilter.keyword) }"
                @click="clearAdminGroupFilter(true)"
              >
                全院学员
              </a>
            </el-breadcrumb-item>
            <el-breadcrumb-item v-if="selectedMentorGroup || studyFilter.keyword">
              <span class="bc-current">带教组：{{ selectedMentorGroup || studyFilter.keyword }}</span>
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <!-- 常驻高可见筛选状态提示条 -->
        <div v-if="selectedMentorGroup || studyFilter.keyword" class="filter-status-banner">
          <div class="fsb-left">
            <el-icon class="fsb-icon"><Filter /></el-icon>
            <span class="fsb-title">已按带教组筛选：</span>
            <el-tag size="small" type="success" closable @close="clearAdminGroupFilter(true)">
              {{ selectedMentorGroup || studyFilter.keyword }}
            </el-tag>
            <span class="fsb-count">（共匹配到 <strong>{{ studyTotal }}</strong> 名学员）</span>
          </div>
          <div class="fsb-actions">
            <el-button type="primary" size="small" :icon="Back" @click="clearAdminGroupFilter(true)">
              返回全部学员
            </el-button>
            <el-button size="small" :icon="RefreshLeft" @click="clearAdminGroupFilter(true)">
              清除筛选
            </el-button>
            <el-tooltip content="清除筛选，返回全部学员" placement="top">
              <button class="fsb-close-circle" type="button" @click="clearAdminGroupFilter(true)" aria-label="清除筛选">
                <el-icon><Close /></el-icon>
              </button>
            </el-tooltip>
          </div>
        </div>
        <el-table
          v-loading="studyLoading"
          :data="studyList"
          size="small"
          stripe
          class="study-table"
          @row-click="openStudentDrilldown"
        >
          <el-table-column type="index" label="#" width="56" />
          <el-table-column prop="username" label="账号" width="130" />
          <el-table-column prop="realName" label="姓名" width="120">
            <template #default="{ row }">
              <strong>{{ row.realName || row.username }}</strong>
            </template>
          </el-table-column>
          <el-table-column prop="department" label="科室" min-width="150">
            <template #default="{ row }">
              <span v-if="row.department">{{ row.department }}</span>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
          <el-table-column label="学时（小时）" width="150" sortable :sort-by="(r: StudyHoursItem) => r.totalHours">
            <template #default="{ row }">
              <b>{{ row.totalHours.toFixed(2) }}</b>
              <span class="muted ml8">{{ row.totalSeconds }} 秒</span>
            </template>
          </el-table-column>
          <el-table-column label="练习次数" width="100" sortable :sort-by="(r: StudyHoursItem) => r.practiceCount" prop="practiceCount" />
          <el-table-column prop="caseCount" label="完成病例" width="100" sortable />
          <el-table-column label="平均成绩" width="100" sortable :sort-by="(r: StudyHoursItem) => r.avgScore">
            <template #default="{ row }">
              <span :class="row.avgScore >= 60 ? 'text-pass' : 'text-fail'">
                {{ row.avgScore.toFixed(1) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="平均 IoU" width="170" sortable :sort-by="(r: StudyHoursItem) => r.avgIou">
            <template #default="{ row }">
              <el-progress
                :percentage="Number((row.avgIou * 100).toFixed(1))"
                :stroke-width="8"
                :show-text="false"
                :color="row.avgIou >= 0.6 ? '#00b42a' : row.avgIou >= 0.4 ? '#ff7d00' : '#f53f3f'"
                style="width: 85px; display: inline-block; vertical-align: middle"
              />
              <span class="conf-num">{{ (row.avgIou * 100).toFixed(1) }}%</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openStudentDrilldown(row)">
                查看学情
              </el-button>
            </template>
          </el-table-column>
          <template #empty>
            <div class="empty">{{ studyLoading ? '加载中…' : '暂无学员学时数据' }}</div>
          </template>
        </el-table>
        <div v-if="studyTotal > studyPagination.pageSize" class="pagination">
          <el-pagination
            v-model:current-page="studyPagination.page"
            v-model:page-size="studyPagination.pageSize"
            :total="studyTotal"
            :page-sizes="[20, 50, 100, 200]"
            background
            layout="total, sizes, prev, pager, next, jumper"
            @size-change="fetchStudy"
            @current-change="fetchStudy"
          />
        </div>
      </div>

      <!-- 共享学员学情抽屉（四层下钻第3层） -->
      <StudentDrilldownDrawer
        v-model="studentDrawerOpen"
        :student="selectedStudent"
        :can-edit-group="true"
        @group-updated="onGroupUpdated"
      />

      <!-- 全院核心指标穿透弹窗（四层下钻第1层） -->
      <KpiDrilldownDialog
        v-model="kpiModalVisible"
        :kpi-type="kpiModalType"
        :title="kpiModalTitle"
        :students="rotationHome?.students || []"
        :overview="overview"
        @select-student="onSelectStudentFromKpi"
      />

      <!-- 常见漏诊误诊穿透弹窗（四层下钻第4层） -->
      <WeakCaseListDialog
        v-model="weakModalVisible"
        :title="weakModalTitle"
        :label="weakModalLabel"
        :error-type="weakModalType"
        :study-year="weakModalGroup?.studyYear"
        :rotation-batch="weakModalGroup?.rotationBatch"
        :mentor-group="weakModalGroup?.mentorGroup"
      />
    </template>
  </div>
</template>

<style scoped>
.card {
  background: var(--hy-c-surface, #fff);
  border: 1px solid var(--hy-c-border, #e5e6eb);
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 18px;
}
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  flex-wrap: wrap;
  gap: 10px;
}
.card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--hy-c-text, #1d2129);
}
.card-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.muted {
  color: var(--hy-c-text-3, #86909c);
  font-size: 12px;
  font-weight: 400;
}
.ml8 {
  margin-left: 8px;
}
.empty {
  padding: 36px 0;
  text-align: center;
  color: var(--hy-c-text-4, #c9cdd4);
  font-size: 14px;
}
.pagination {
  margin-top: 14px;
  display: flex;
  justify-content: flex-end;
}

.overview-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 16px;
  margin-bottom: 18px;
}
.ov-card {
  background: var(--hy-c-surface, #fff);
  border: 1px solid var(--hy-c-border, #e5e6eb);
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  align-items: center;
  gap: 14px;
}
.ov-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  font-size: 22px;
  background: var(--hy-c-primary-soft, #eef4ff);
  color: #1677ff;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ov-icon.green {
  background: rgba(0, 180, 42, 0.12);
  color: #00b42a;
}
.ov-icon.blue {
  background: rgba(22, 119, 255, 0.12);
  color: #1677ff;
}
.ov-info .ov-num {
  font-size: 22px;
  font-weight: 700;
  color: var(--hy-c-text, #1d2129);
  line-height: 1.2;
}
.ov-info .ov-num.small {
  font-size: 14px;
}
.ov-info .ov-label {
  font-size: 12px;
  color: var(--hy-c-text-3, #86909c);
  margin-top: 2px;
}
.green-text { color: #00b42a; }
.blue-text { color: #1677ff; }
.refresh-card {
  cursor: pointer;
  transition: 0.2s;
}
.refresh-card:hover {
  border-color: #1677ff;
  background: var(--hy-c-primary-soft, #f7faff);
}

.distrib-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
.bar-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.bar-row {
  display: grid;
  grid-template-columns: 110px 1fr 60px;
  gap: 10px;
  align-items: center;
  font-size: 13px;
}
.bar-label {
  color: var(--hy-c-text-2, #4e5969);
}
.bar-track {
  background: var(--hy-c-fill, #f2f3f5);
  border-radius: 4px;
  height: 12px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 4px;
  background: linear-gradient(90deg, #4091ff, #1677ff);
  transition: width 0.3s;
}
.bar-fill.dr {
  background: linear-gradient(90deg, #00b42a, #ff7d00, #f53f3f);
}
.bar-value {
  text-align: right;
  font-weight: 600;
  color: var(--hy-c-text, #1d2129);
}
.conf-num {
  margin-left: 6px;
  font-size: 12px;
  color: var(--hy-c-text-2, #4e5969);
  vertical-align: middle;
}

.clickable-ov-card {
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.clickable-ov-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border-color: #1677ff;
}
.ov-drill {
  font-size: 12px;
  color: #1677ff;
  margin-left: 2px;
}
.clickable-bar {
  cursor: pointer;
  padding: 4px 6px;
  border-radius: 4px;
  transition: background-color 0.15s ease;
}
.clickable-bar:hover {
  background-color: var(--hy-c-fill, #f2f3f5);
}
.admin-group-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 10px;
}
.admin-group-card {
  background: var(--hy-c-fill, #f7f9fb);
  border: 1px solid var(--hy-c-border, #e5e6eb);
  border-radius: 10px;
  padding: 14px 16px;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}
.admin-group-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  border-color: #1677ff;
}
.admin-group-card.is-selected {
  border-color: #1677ff !important;
  background-color: #f0f7ff !important;
  box-shadow: 0 0 0 2px rgba(22, 119, 255, 0.25) !important;
}
.group-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.filter-link {
  font-size: 12px;
  color: #1677ff;
}
.filter-link.is-active {
  color: #1677ff;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.drilldown-breadcrumb-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 10px;
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
  color: #1677ff !important;
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
  color: #1677ff;
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
  color: #1677ff;
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
.group-info {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--hy-c-text-2, #4e5969);
}
.weak-tags {
  margin-top: 8px;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}
.weak-lbl {
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
.study-table :deep(tr.el-table__row) {
  cursor: pointer;
}
.text-pass {
  color: #00b42a;
  font-weight: 600;
}
.text-fail {
  color: #f53f3f;
  font-weight: 600;
}
.mt6 {
  margin-top: 6px;
}
.mt16 {
  margin-top: 16px;
}
.font12 {
  font-size: 12px;
}

@media (max-width: 1280px) {
  .overview-grid {
    grid-template-columns: repeat(3, 1fr);
  }
  .distrib-grid {
    grid-template-columns: 1fr;
  }
  .admin-group-grid {
    grid-template-columns: 1fr;
  }
}
</style>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { PracticeApi, RotationApi } from '@/api'
import type { PracticeRecord, PracticeStats } from '@/api/practice'
import { actorLabel } from '@/utils/actor'
import WeakCaseListDialog from './WeakCaseListDialog.vue'

interface StudentBase {
  userId: number
  name: string
  username?: string
  studyYear?: string
  rotationBatch?: string
  mentorGroup?: string
  groupEditorName?: string
  groupEditorRole?: string
  groupEditedAt?: string | null
}

const props = defineProps<{
  modelValue: boolean
  student: StudentBase | null
  canEditGroup?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'groupUpdated'): void
}>()

const router = useRouter()
const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const loading = ref(false)
const studentStats = ref<PracticeStats | null>(null)
const studentRecords = ref<PracticeRecord[]>([])
const commentDraft = ref<Record<number, string>>({})
const savingCommentId = ref(0)
const savingGroup = ref(false)

const groupDraft = reactive({
  studyYear: '',
  rotationBatch: '',
  mentorGroup: ''
})

// 漏诊误诊明细弹窗
const weakModalVisible = ref(false)
const weakModalLabel = ref('')
const weakModalType = ref<'missed' | 'false_positive' | ''>('')

const formatMinutes = (seconds: number) => {
  if (!seconds) return '0 分钟'
  if (seconds < 60) return '不足 1 分钟'
  return `${Math.round(seconds / 60)} 分钟`
}

const finishedRecords = computed(() =>
  studentRecords.value
    .filter((row) => row.status === 'SUBMITTED' || row.status === 'REVIEWED')
    .slice()
    .sort((a, b) => (a.submittedAt || a.createdAt || '').localeCompare(b.submittedAt || b.createdAt || ''))
)

const retryChanges = computed(() => {
  const groups = new Map<number, PracticeRecord[]>()
  finishedRecords.value.forEach((row) => {
    const list = groups.get(row.caseId) || []
    list.push(row)
    groups.set(row.caseId, list)
  })
  return [...groups.values()]
    .filter((list) => list.length >= 2)
    .map((list) => {
      const first = list[0]
      const last = list[list.length - 1]
      const delta = Math.round((last.scoreTotal - first.scoreTotal) * 10) / 10
      return {
        caseNo: last.caseNo || first.caseNo,
        times: list.length,
        first: first.scoreTotal,
        last: last.scoreTotal,
        delta
      }
    })
})

const loadData = async () => {
  if (!props.student) return
  const stu = props.student
  groupDraft.studyYear = stu.studyYear === '未分组' ? '' : stu.studyYear || ''
  groupDraft.rotationBatch = stu.rotationBatch === '未分组' ? '' : stu.rotationBatch || ''
  groupDraft.mentorGroup = stu.mentorGroup === '未分组' ? '' : stu.mentorGroup || ''

  loading.value = true
  studentStats.value = null
  studentRecords.value = []
  commentDraft.value = {}

  try {
    const [stats, page] = await Promise.all([
      PracticeApi.getUserStats(stu.userId),
      PracticeApi.getPracticeList({ userId: stu.userId, page: 1, pageSize: 200 })
    ])
    studentStats.value = stats
    studentRecords.value = page?.list || []
    const drafts: Record<number, string> = {}
    studentRecords.value.forEach((item) => {
      drafts[item.id] = item.teacherComment || ''
    })
    commentDraft.value = drafts
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  (val) => {
    if (val && props.student) loadData()
  }
)

const saveGroup = async () => {
  if (!props.student) return
  savingGroup.value = true
  try {
    await RotationApi.setStudentGroup(props.student.userId, {
      studyYear: groupDraft.studyYear,
      rotationBatch: groupDraft.rotationBatch,
      mentorGroup: groupDraft.mentorGroup
    })
    ElMessage.success('分组已保存')
    emit('groupUpdated')
  } finally {
    savingGroup.value = false
  }
}

const saveComment = async (row: PracticeRecord) => {
  const text = (commentDraft.value[row.id] || '').trim()
  if (!text) {
    ElMessage.warning('请先写评语')
    return
  }
  savingCommentId.value = row.id
  try {
    const saved = await PracticeApi.reviewPractice(row.id, text)
    const index = studentRecords.value.findIndex((item) => item.id === row.id)
    if (index >= 0) studentRecords.value[index] = saved
    commentDraft.value[row.id] = saved.teacherComment || text
  } finally {
    savingCommentId.value = 0
  }
}

const openWeakModal = (label: string, type: 'missed' | 'false_positive') => {
  weakModalLabel.value = label
  weakModalType.value = type
  weakModalVisible.value = true
}

const openWorkstation = (record: PracticeRecord) => {
  visible.value = false
  router.push({
    path: '/training/practice/workstation',
    query: {
      caseId: String(record.caseId),
      sessionId: String(record.id),
      view: 'report'
    }
  })
}
</script>

<template>
  <el-drawer
    v-model="visible"
    :title="student ? `${student.name} 的学情明细` : '学情明细'"
    size="760px"
    destroy-on-close
    append-to-body
    class="student-drilldown-drawer"
  >
    <div v-loading="loading">
      <!-- 分组管理（教师/管理员有权限） -->
      <section v-if="canEditGroup !== false" class="block">
        <h3>带教分组</h3>
        <div class="assign">
          <el-input v-model="groupDraft.studyYear" placeholder="年级，如 2024级" style="width: 170px" />
          <el-input v-model="groupDraft.rotationBatch" placeholder="轮转批次，如 2026年上半年" style="width: 200px" />
          <el-input v-model="groupDraft.mentorGroup" placeholder="带教组" style="width: 150px" />
          <el-button type="primary" :loading="savingGroup" @click="saveGroup">保存分组</el-button>
        </div>
        <p v-if="student" class="lead-note">
          {{
            actorLabel(student.groupEditorName, student.groupEditorRole)
              ? `最近由 ${actorLabel(student.groupEditorName, student.groupEditorRole)}${student.groupEditedAt ? ` 于 ${student.groupEditedAt}` : ''} 修改`
              : '保存后将记录修改人与时间'
          }}
        </p>
      </section>

      <!-- 核心指标 -->
      <div v-if="studentStats" class="stats detail-stats">
        <article>
          <span>练习次数</span>
          <strong>{{ studentStats.submittedSessions }}</strong>
        </article>
        <article>
          <span>完成病例</span>
          <strong>{{ studentStats.completedCases }}</strong>
        </article>
        <article>
          <span>平均成绩</span>
          <strong>{{ studentStats.avgScore.toFixed(1) }}</strong>
        </article>
        <article>
          <span>在机学时</span>
          <strong>{{ formatMinutes(studentStats.totalDuration) }}</strong>
        </article>
      </div>

      <!-- 常见漏诊与误诊（支持下钻到第 4 层题目与病例） -->
      <section class="block">
        <div class="block-head">
          <h3>常见漏诊和误诊</h3>
          <span class="muted font12">点击漏诊/误诊数字可穿透具体题目与影像</span>
        </div>
        <el-table v-if="studentStats?.weakLabels?.length" :data="studentStats.weakLabels" size="small" border>
          <el-table-column prop="label" label="病灶类别" min-width="140">
            <template #default="{ row }">
              <strong>{{ row.label }}</strong>
            </template>
          </el-table-column>
          <el-table-column label="漏诊次数" width="110">
            <template #default="{ row }">
              <el-button
                v-if="row.missed > 0"
                link
                type="danger"
                size="small"
                @click="openWeakModal(row.label, 'missed')"
              >
                <b>{{ row.missed }}</b> 次 &gt;
              </el-button>
              <span v-else class="muted">0</span>
            </template>
          </el-table-column>
          <el-table-column label="误诊次数" width="110">
            <template #default="{ row }">
              <el-button
                v-if="row.falsePositive > 0"
                link
                type="warning"
                size="small"
                @click="openWeakModal(row.label, 'false_positive')"
              >
                <b>{{ row.falsePositive }}</b> 次 &gt;
              </el-button>
              <span v-else class="muted">0</span>
            </template>
          </el-table-column>
        </el-table>
        <p v-else class="empty">还没有汇总出漏诊或误诊。</p>
      </section>

      <!-- 复练后的成绩变化 -->
      <section class="block">
        <h3>复练成绩演进</h3>
        <div v-if="retryChanges.length" class="retry-list">
          <p v-for="item in retryChanges" :key="item.caseNo" class="lead-note">
            <b>{{ item.caseNo }}</b> 练习 {{ item.times }} 次：从 {{ item.first }} 分到 {{ item.last }} 分，
            <span :class="item.delta > 0 ? 'text-up' : item.delta < 0 ? 'text-down' : 'muted'">
              {{ item.delta > 0 ? `提高 ${item.delta} 分` : item.delta < 0 ? `下降 ${Math.abs(item.delta)} 分` : '分数持平' }}
            </span>。
          </p>
        </div>
        <p v-else class="empty">同一病例还没有多次已交卷的练习对比。</p>
      </section>

      <!-- 已完成病例明细台账 -->
      <section class="block">
        <h3>已完成病例和得分</h3>
        <el-table :data="finishedRecords" size="small" stripe empty-text="还没有交卷记录">
          <el-table-column label="交卷时间" width="135">
            <template #default="{ row }">{{ (row.submittedAt || '').slice(0, 16) || '—' }}</template>
          </el-table-column>
          <el-table-column label="病例编号" width="110">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openWorkstation(row)">
                {{ row.caseNo }}
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="得分" width="75">
            <template #default="{ row }">
              <span :class="row.scoreTotal >= 60 ? 'text-pass' : 'text-fail'">
                {{ row.scoreTotal }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="用时" width="95">
            <template #default="{ row }">{{ formatMinutes(row.durationSeconds) }}</template>
          </el-table-column>
          <el-table-column label="漏诊/误诊" width="95">
            <template #default="{ row }">
              <span :class="{ 'text-fail': row.missedCount > 0 }">{{ row.missedCount }}</span>
              /
              <span :class="{ 'text-fail': row.falsePositiveCount > 0 }">{{ row.falsePositiveCount }}</span>
            </template>
          </el-table-column>
          <el-table-column label="教师点评" min-width="210">
            <template #default="{ row }">
              <div class="comment-line">
                <el-input v-model="commentDraft[row.id]" size="small" placeholder="写一句评语" />
                <el-button
                  size="small"
                  type="primary"
                  :loading="savingCommentId === row.id"
                  @click="saveComment(row)"
                >
                  保存
                </el-button>
              </div>
              <p v-if="row.teacherName" class="lead-note">
                点评人 {{ actorLabel(row.teacherName, row.teacherRole) }}
              </p>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openWorkstation(row)">
                查看判读
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </section>
    </div>

    <!-- 漏诊误诊穿透弹窗 -->
    <WeakCaseListDialog
      v-model="weakModalVisible"
      :label="weakModalLabel"
      :error-type="weakModalType"
      :user-id="student?.userId"
      :student-name="student?.name"
      :title="`${student?.name || ''} - ${weakModalLabel} ${weakModalType === 'missed' ? '漏诊' : '误诊'}明细`"
    />
  </el-drawer>
</template>

<style scoped>
.block {
  margin-bottom: 24px;
}
.block-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 8px;
}
.assign {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.lead-note {
  font-size: 12px;
  color: #8f959e;
  margin: 6px 0 0;
}
.stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 24px;
}
.detail-stats article {
  background: #f7f8fa;
  border-radius: 8px;
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
}
.detail-stats article span {
  font-size: 12px;
  color: #646a73;
}
.detail-stats article strong {
  font-size: 20px;
  color: #1f2329;
  margin-top: 4px;
}
.comment-line {
  display: flex;
  gap: 6px;
  align-items: center;
}
.text-pass {
  color: #00b42a;
  font-weight: 600;
}
.text-fail {
  color: #f53f3f;
  font-weight: 600;
}
.text-up {
  color: #00b42a;
  font-weight: 600;
}
.text-down {
  color: #f53f3f;
  font-weight: 600;
}
.muted {
  color: #8f959e;
}
.font12 {
  font-size: 12px;
}
.empty {
  color: #8f959e;
  font-size: 13px;
  padding: 12px 0;
}
</style>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { StudentProgress } from '@/api/rotation'
import type { CommonApi } from '@/api'

type TrainingOverview = CommonApi.TrainingOverview

const props = defineProps<{
  modelValue: boolean
  kpiType: 'students' | 'practice' | 'avgScore' | 'studyHours' | 'cases' | 'passRate'
  students?: StudentProgress[]
  overview?: TrainingOverview | null
  title?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'selectStudent', student: StudentProgress): void
}>()

const router = useRouter()
const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const studentTab = ref<'all' | 'done' | 'pending'>('all')

const studentList = computed(() => props.students || [])

const filteredStudents = computed(() => {
  if (props.kpiType !== 'students') return studentList.value
  if (studentTab.value === 'done') {
    return studentList.value.filter((s) => s.practiceCount > 0)
  }
  if (studentTab.value === 'pending') {
    return studentList.value.filter((s) => s.practiceCount === 0)
  }
  return studentList.value
})

const sortedByScore = computed(() => {
  return [...studentList.value].sort((a, b) => b.avgScore - a.avgScore)
})

const sortedByHours = computed(() => {
  return [...studentList.value].sort((a, b) => b.studySeconds - a.studySeconds)
})

const scoreDistribution = computed(() => {
  let g90 = 0, g80 = 0, g60 = 0, l60 = 0
  studentList.value.forEach((s) => {
    if (s.avgScore >= 90) g90++
    else if (s.avgScore >= 80) g80++
    else if (s.avgScore >= 60) g60++
    else l60++
  })
  return { g90, g80, g60, l60 }
})

const formatMinutes = (seconds: number) => {
  if (!seconds) return '0 分钟'
  if (seconds < 60) return '不足 1 分钟'
  return `${Math.round(seconds / 60)} 分钟`
}

const onStudentClick = (stu: StudentProgress) => {
  emit('selectStudent', stu)
}

const goToCases = () => {
  visible.value = false
  router.push('/training/cases')
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="title || '指标下钻明细'"
    width="900px"
    destroy-on-close
    append-to-body
    class="kpi-drilldown-dialog"
  >
    <!-- 1. 学员数下钻（名单 + 已交卷 / 未交卷） -->
    <div v-if="kpiType === 'students'">
      <div class="kpi-tabs-head">
        <el-radio-group v-model="studentTab" size="small">
          <el-radio-button label="all">全部学员 ({{ studentList.length }})</el-radio-button>
          <el-radio-button label="done">
            已交卷 ({{ studentList.filter((s) => s.practiceCount > 0).length }})
          </el-radio-button>
          <el-radio-button label="pending">
            未交卷 ({{ studentList.filter((s) => s.practiceCount === 0).length }})
          </el-radio-button>
        </el-radio-group>
      </div>

      <el-table :data="filteredStudents" size="small" stripe max-height="460">
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="name" label="姓名" width="110">
          <template #default="{ row }">
            <strong>{{ row.name }}</strong>
          </template>
        </el-table-column>
        <el-table-column prop="username" label="账号" width="120" />
        <el-table-column prop="studyYear" label="年级" width="100" />
        <el-table-column prop="mentorGroup" label="带教组" width="110" />
        <el-table-column label="已练次数" width="90">
          <template #default="{ row }">
            <span :class="row.practiceCount > 0 ? 'text-pass' : 'text-pending'">
              {{ row.practiceCount }} 次
            </span>
          </template>
        </el-table-column>
        <el-table-column prop="completedCases" label="完成病例" width="90" />
        <el-table-column label="平均成绩" width="90">
          <template #default="{ row }">{{ row.avgScore.toFixed(1) }}</template>
        </el-table-column>
        <el-table-column label="在机学时" width="110">
          <template #default="{ row }">{{ formatMinutes(row.studySeconds) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="onStudentClick(row)">
              查看学情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 2. 练习次数下钻 -->
    <div v-else-if="kpiType === 'practice'">
      <p class="summary-tip">全班学员练习交卷明细分布</p>
      <el-table :data="studentList" size="small" stripe max-height="460">
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="name" label="学员" width="120">
          <template #default="{ row }">
            <strong>{{ row.name }}</strong>
          </template>
        </el-table-column>
        <el-table-column prop="mentorGroup" label="带教组" width="120" />
        <el-table-column label="累计练习次数" width="120">
          <template #default="{ row }">
            <b>{{ row.practiceCount }}</b> 次
          </template>
        </el-table-column>
        <el-table-column label="完成病例数" width="110">
          <template #default="{ row }">{{ row.completedCases }} 例</template>
        </el-table-column>
        <el-table-column label="必做任务进度" min-width="140">
          <template #default="{ row }">
            <el-progress :percentage="row.progress" :stroke-width="6" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="onStudentClick(row)">
              查看明细
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 3. 平均分下钻（分数段 + 逐人得分排行） -->
    <div v-else-if="kpiType === 'avgScore'">
      <div class="score-cards">
        <div class="score-card green">
          <div class="sc-num">{{ scoreDistribution.g90 }}</div>
          <div class="sc-label">优秀 (≥90分)</div>
        </div>
        <div class="score-card blue">
          <div class="sc-num">{{ scoreDistribution.g80 }}</div>
          <div class="sc-label">良好 (80-89分)</div>
        </div>
        <div class="score-card orange">
          <div class="sc-num">{{ scoreDistribution.g60 }}</div>
          <div class="sc-label">及格 (60-79分)</div>
        </div>
        <div class="score-card red">
          <div class="sc-num">{{ scoreDistribution.l60 }}</div>
          <div class="sc-label">待加强 (&lt;60分)</div>
        </div>
      </div>

      <el-table :data="sortedByScore" size="small" stripe max-height="400">
        <el-table-column type="index" label="排名" width="60" />
        <el-table-column prop="name" label="姓名" width="120">
          <template #default="{ row }">
            <strong>{{ row.name }}</strong>
          </template>
        </el-table-column>
        <el-table-column prop="mentorGroup" label="带教组" width="120" />
        <el-table-column label="综合平均分" width="130" sortable :sort-by="(r: StudentProgress) => r.avgScore">
          <template #default="{ row }">
            <span :class="row.avgScore >= 60 ? 'text-pass' : 'text-fail'">
              <b>{{ row.avgScore.toFixed(1) }}</b> 分
            </span>
          </template>
        </el-table-column>
        <el-table-column label="达标判定" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.avgScore >= 60 ? 'success' : 'danger'" effect="plain">
              {{ row.avgScore >= 60 ? '达标' : '未达标' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="practiceCount" label="练习次数" width="100" />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="onStudentClick(row)">
              查看学情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 4. 总学时下钻（排行与明细） -->
    <div v-else-if="kpiType === 'studyHours'">
      <p class="summary-tip">学员有效在机练习操作时长排行（交卷即固化）</p>
      <el-table :data="sortedByHours" size="small" stripe max-height="460">
        <el-table-column type="index" label="学时排名" width="80" />
        <el-table-column prop="name" label="学员" width="130">
          <template #default="{ row }">
            <strong>{{ row.name }}</strong>
          </template>
        </el-table-column>
        <el-table-column prop="mentorGroup" label="带教组" width="130" />
        <el-table-column label="在机学时" min-width="160" sortable :sort-by="(r: StudentProgress) => r.studySeconds">
          <template #default="{ row }">
            <b>{{ formatMinutes(row.studySeconds) }}</b>
            <span class="muted font12 ml8">({{ row.studySeconds }} 秒)</span>
          </template>
        </el-table-column>
        <el-table-column prop="practiceCount" label="练习次数" width="110" />
        <el-table-column prop="completedCases" label="完成病例" width="110" />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="onStudentClick(row)">
              查看学情
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 5. 病例总数下钻（管理员端） -->
    <div v-else-if="kpiType === 'cases'">
      <div v-if="overview" class="overview-box">
        <div class="diff-block">
          <h4>病例难度分布 (共 {{ overview.totalCases }} 例)</h4>
          <div class="tag-list">
            <el-tag v-for="it in overview.byDifficulty" :key="it.label" size="large" class="mr8 mb8">
              {{ it.label }}：{{ it.value }} 例
            </el-tag>
          </div>
        </div>
        <div class="diff-block mt16">
          <h4>DR 分级分布</h4>
          <div class="tag-list">
            <el-tag v-for="it in overview.byDrGrade" :key="it.label" type="success" size="large" class="mr8 mb8">
              {{ it.label }}：{{ it.value }} 例
            </el-tag>
          </div>
        </div>
      </div>
      <div class="mt16 text-center">
        <el-button type="primary" @click="goToCases">前往病例库管理 / 筛选病例</el-button>
      </div>
    </div>

    <!-- 6. 合格率 / 平均 IoU 下钻（管理员端） -->
    <div v-else-if="kpiType === 'passRate'">
      <div v-if="overview" class="rate-box">
        <div class="rate-stat">
          <div class="rate-val">{{ (overview.passRate * 100).toFixed(1) }}%</div>
          <div class="rate-lbl">整体合格率（IoU ≥ 0.6）</div>
        </div>
        <div class="rate-stat">
          <div class="rate-val">{{ (overview.avgIou * 100).toFixed(1) }}%</div>
          <div class="rate-lbl">全院平均 IoU 重合度</div>
        </div>
        <div class="rate-stat">
          <div class="rate-val">{{ overview.totalRecords }}</div>
          <div class="rate-lbl">累计完成答卷总数</div>
        </div>
      </div>
      <p class="muted font12 text-center mt16">
        下方学员学时汇总表格中已列出每位学员的平均成绩与平均 IoU，点击对应学员行可展开其全部答卷明细。
      </p>
    </div>

    <template #footer>
      <div class="text-right">
        <el-button @click="visible = false">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.kpi-tabs-head {
  margin-bottom: 14px;
}
.summary-tip {
  font-size: 13px;
  color: #646a73;
  margin-bottom: 12px;
}
.score-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.score-card {
  padding: 12px 14px;
  border-radius: 8px;
  background: #f7f8fa;
  text-align: center;
}
.score-card.green {
  background: #e8ffea;
  color: #00b42a;
}
.score-card.blue {
  background: #e8f3ff;
  color: #165dff;
}
.score-card.orange {
  background: #fff7e8;
  color: #ff7d00;
}
.score-card.red {
  background: #ffece8;
  color: #f53f3f;
}
.sc-num {
  font-size: 22px;
  font-weight: 700;
}
.sc-label {
  font-size: 12px;
  margin-top: 4px;
  color: #646a73;
}
.rate-box {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  padding: 20px;
  background: #f7f8fa;
  border-radius: 8px;
  text-align: center;
}
.rate-val {
  font-size: 28px;
  font-weight: 700;
  color: #165dff;
}
.rate-lbl {
  font-size: 13px;
  color: #646a73;
  margin-top: 6px;
}
.text-pass {
  color: #00b42a;
  font-weight: 600;
}
.text-fail {
  color: #f53f3f;
  font-weight: 600;
}
.text-pending {
  color: #8f959e;
}
.muted {
  color: #8f959e;
}
.font12 {
  font-size: 12px;
}
.ml8 {
  margin-left: 8px;
}
.mr8 {
  margin-right: 8px;
}
.mb8 {
  margin-bottom: 8px;
}
.mt16 {
  margin-top: 16px;
}
.text-center {
  text-align: center;
}
.text-right {
  text-align: right;
}
</style>

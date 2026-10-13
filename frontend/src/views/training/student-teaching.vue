<script setup lang="ts">
/**
 * 教师演示病例（学员端）
 * - 列出可见的临时分享 + 已入库教学病例
 * - 学员仅可查看脱敏数据 + 点击实训
 * - 已入库的可走练习流程；临时分享仅用于查看（脱敏只读）
 */
import { computed, onActivated, onBeforeUnmount, onDeactivated, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, View, Pointer, Picture } from '@element-plus/icons-vue'
import { PracticeApi, TeachingApi } from '@/api'
import TeachingDemoBody from './components/TeachingDemoBody.vue'
import TeachingOutlineView from '@/components/TeachingOutlineView.vue'

type StudentCase = TeachingApi.StudentCase

const router = useRouter()

const list = ref<StudentCase[]>([])
const loading = ref(false)
const pagination = reactive({ page: 1, pageSize: 20, total: 0 })

const fetchList = async () => {
  loading.value = true
  try {
    const r = await TeachingApi.getStudentCases({
      page: pagination.page,
      pageSize: pagination.pageSize,
    })
    list.value = r?.list || []
    pagination.total = r?.total || 0
  } catch {
    list.value = []
    pagination.total = 0
  } finally {
    loading.value = false
  }
}

const brokenThumbs = reactive<Record<number, boolean>>({})
const firstImage = (c: StudentCase) => {
  if (brokenThumbs[c.id]) return ''
  const paths = c.imagePaths || {}
  for (const side of ['OD', 'OS', 'OU', 'UK']) {
    const arr = paths[side]
    if (Array.isArray(arr) && arr[0]) return arr[0]
  }
  for (const arr of Object.values(paths)) {
    if (Array.isArray(arr) && arr[0]) return arr[0]
  }
  return ''
}

const categoryOf = (c: StudentCase) => c.categoryText || c.category || ''
const difficultyOf = (c: StudentCase) => c.difficultyText || c.difficulty || ''
// 未公布结论的病例不参与分级筛选，避免通过筛选结果反推出答案
const gradeOf = (c: StudentCase) => (c.answersRevealed === false ? '' : c.goldGradeText || '')

const DIFFICULTY_RANK: Record<string, number> = {
  入门: 1, 基础: 1, EASY: 1, BASIC: 1,
  中等: 2, 中级: 2, MEDIUM: 2,
  进阶: 3, 高阶: 3, 困难: 3, HARD: 3, ADVANCED: 3,
}
const rankOf = (c: StudentCase) =>
  DIFFICULTY_RANK[c.difficultyText || ''] ?? DIFFICULTY_RANK[(c.difficulty || '').toUpperCase()] ?? 99

const filters = reactive({ category: '', grade: '', difficulty: '', sort: 'latest' })
const uniq = (vals: string[]) => [...new Set(vals.filter(Boolean))]
const categoryOptions = computed(() => uniq(list.value.map(categoryOf)))
const gradeOptions = computed(() => uniq(list.value.map(gradeOf)))
const difficultyOptions = computed(() =>
  uniq(list.value.map(difficultyOf)).sort(
    (a, b) => (DIFFICULTY_RANK[a] ?? 99) - (DIFFICULTY_RANK[b] ?? 99),
  ),
)
const hasActiveFilter = computed(() => !!(filters.category || filters.grade || filters.difficulty))
const clearFilters = () => {
  filters.category = ''
  filters.grade = ''
  filters.difficulty = ''
}

const visibleList = computed(() => {
  const out = list.value.filter(
    (c) =>
      (!filters.category || categoryOf(c) === filters.category) &&
      (!filters.grade || gradeOf(c) === filters.grade) &&
      (!filters.difficulty || difficultyOf(c) === filters.difficulty),
  )
  if (filters.sort === 'easy') return [...out].sort((a, b) => rankOf(a) - rankOf(b))
  if (filters.sort === 'hard') return [...out].sort((a, b) => rankOf(b) - rankOf(a))
  return out
})

const detailVisible = ref(false)
const detail = ref<StudentCase | null>(null)
const detailLoading = ref(false)
const showDetail = async (row: StudentCase) => {
  detailVisible.value = true
  detail.value = null
  detailLoading.value = true
  try {
    detail.value = await TeachingApi.getStudentCaseDetail(row.id)
  } catch {
    detailVisible.value = false
  } finally {
    detailLoading.value = false
  }
}

const onPractice = async (row: StudentCase) => {
  if (!row.teachingCaseId) {
    ElMessage.warning('该临时演示病例暂不支持启动正式练习，可点击查看进入只读阅片')
    return
  }
  try {
    const r = await PracticeApi.startPractice({
      caseId: row.teachingCaseId,
      mode: 'SELECTED',
    })
    router.push({
      path: '/training/practice/workstation',
      query: { sessionId: String(r.id), caseId: String(row.teachingCaseId) },
    })
  } catch {
    /* 已弹错误 */
  }
}

const POLL_MS = 60_000
let pollTimer: ReturnType<typeof setInterval> | null = null
let firstActivation = true

const startPolling = () => {
  stopPolling()
  pollTimer = setInterval(() => {
    if (document.visibilityState === 'visible' && !loading.value) fetchList()
  }, POLL_MS)
}
const stopPolling = () => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

onMounted(() => {
  fetchList()
  startPolling()
})
// 页面被 keep-alive 缓存：切回来时重新拉取，老师上架 / 收回 / 改范围后无需手动刷新
onActivated(() => {
  if (firstActivation) {
    firstActivation = false
    return
  }
  fetchList()
  startPolling()
})
onDeactivated(stopPolling)
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="student-teaching-page">
    <header class="page-head">
      <div class="head-left">
        <h2>教师演示病例</h2>
        <div class="muted">课堂分享可能先不公布结论，请先独立判断（共 {{ pagination.total }} 份）</div>
        <div class="muted small">只显示发给你所在分组且仍在有效期内的病例；老师收回、下架或分享过期后会自动从这里消失。</div>
      </div>
      <div class="head-right">
        <el-button :icon="Refresh" size="small" @click="fetchList">刷新</el-button>
      </div>
    </header>

    <div v-if="list.length > 0" class="filter-bar" role="group" aria-label="筛选与排序">
      <el-select v-model="filters.category" placeholder="全部病种" clearable size="small" style="width: 140px">
        <el-option v-for="o in categoryOptions" :key="o" :label="o" :value="o" />
      </el-select>
      <el-select v-model="filters.grade" placeholder="全部分级" clearable size="small" style="width: 160px">
        <el-option v-for="o in gradeOptions" :key="o" :label="o" :value="o" />
      </el-select>
      <el-select v-model="filters.difficulty" placeholder="全部难度" clearable size="small" style="width: 120px">
        <el-option v-for="o in difficultyOptions" :key="o" :label="o" :value="o" />
      </el-select>
      <el-select v-model="filters.sort" size="small" style="width: 150px" aria-label="排序">
        <el-option label="最新分享" value="latest" />
        <el-option label="难度由低到高" value="easy" />
        <el-option label="难度由高到低" value="hard" />
      </el-select>
      <el-button v-if="hasActiveFilter" size="small" link type="primary" @click="clearFilters">清除筛选</el-button>
    </div>

    <div v-loading="loading" class="case-grid">
      <el-empty
        v-if="!loading && list.length === 0"
        class="grid-empty"
        description="老师还没给你分享病例，分享后会出现在这里。"
      />
      <el-empty
        v-else-if="!loading && visibleList.length === 0"
        class="grid-empty"
        description="没有符合筛选条件的病例，换个条件试试。"
      >
        <el-button size="small" @click="clearFilters">清除筛选</el-button>
      </el-empty>

      <article v-for="c in visibleList" :key="c.id" class="case-card">
        <div class="thumb">
          <img
            v-if="firstImage(c)"
            :src="firstImage(c)"
            :alt="`${c.title || '教学病例'} 眼底图`"
            loading="lazy"
            @error="brokenThumbs[c.id] = true"
          />
          <div v-else class="thumb-fallback" aria-hidden="true">
            <el-icon :size="30"><Picture /></el-icon>
            <span>暂无眼底图</span>
          </div>
          <span class="kind-badge">教师演示病例</span>
          <span v-if="c.imageCount > 1" class="count-badge">共 {{ c.imageCount }} 张</span>
        </div>

        <div class="card-head">
          <span class="sub-tag" :class="c.shareType === 'PERMANENT' ? 'is-lib' : 'is-temp'">
            {{ c.shareType === 'PERMANENT' ? '入库教学' : '临时分享' }}
          </span>
          <span v-if="c.expiredAt && c.shareType === 'TEMPORARY'" class="muted small">
            到期：{{ c.expiredAt }}
          </span>
        </div>
        <h3 class="card-title">{{ c.title || '教学病例' }}</h3>
        <div class="meta-line">
          <span class="muted small">{{ c.teacherName ? `${c.teacherName} 老师` : '—' }}</span>
          <span v-if="c.categoryText || c.category" class="dot">·</span>
          <span v-if="c.categoryText || c.category" class="muted small">{{ c.categoryText || c.category }}</span>
          <span v-if="c.difficultyText || c.difficulty" class="dot">·</span>
          <span v-if="c.difficultyText || c.difficulty" class="muted small">{{ c.difficultyText || c.difficulty }}</span>
        </div>
        <div class="patient-line">
          <span class="muted small">影像 {{ c.imageCount }} 张</span>
        </div>
        <div v-if="c.answersRevealed === false" class="desc">请先独立判断，老师讨论结束后会公布标准结论。</div>
        <template v-else>
          <div v-if="c.goldGradeText" class="grade">{{ c.goldGradeText }}</div>
          <div v-if="c.teachingPoints" class="desc multiline">
            <span class="kicker">先看</span>
            <TeachingOutlineView :text="c.teachingPoints" tone="dark" />
          </div>
          <div v-else-if="c.goldDiagnosis" class="desc multiline">{{ c.goldDiagnosis }}</div>
          <div v-else class="desc">这份分享还没有带教讲解</div>
        </template>

        <div class="card-actions">
          <el-button
            v-if="c.teachingCaseId"
            type="primary"
            size="small"
            :icon="Pointer"
            @click="onPractice(c)"
          >
            开始判读
          </el-button>
          <el-button
            size="small"
            :type="c.teachingCaseId ? 'default' : 'primary'"
            :icon="View"
            @click="showDetail(c)"
          >
            查看详情
          </el-button>
        </div>
      </article>
    </div>

    <div v-if="pagination.total > pagination.pageSize" class="pagination">
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.pageSize"
        :total="pagination.total"
        :page-sizes="[10, 20, 50]"
        background
        layout="total, sizes, prev, pager, next, jumper"
        @size-change="fetchList"
        @current-change="fetchList"
      />
    </div>

    <!-- 详情对话框（只读） -->
    <el-dialog v-model="detailVisible" :title="detail?.title || '演示病例'" width="920">
      <div v-loading="detailLoading" class="detail-body">
        <template v-if="detail">
          <div class="hint">
            <el-tag size="small" type="info">教学演示</el-tag>
            <span class="who">
              {{ detail.teacherName ? `${detail.teacherName} 老师` : '带教' }}
            </span>
          </div>
          <TeachingDemoBody :source="detail" />
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.student-teaching-page {
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px 28px 36px;
}
.page-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-bottom: 18px;
  gap: 12px;
  flex-wrap: wrap;
}
.head-left h2 { margin: 0 0 4px; font-size: 22px; font-weight: 700; color: var(--hy-c-text, #1e293b); }
.head-left .muted { color: var(--hy-c-text-2, #475569); font-size: 13px; }

.case-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 14px;
  min-height: 200px;
}
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}
.grid-empty { grid-column: 1 / -1; }

/* 教师演示病例：主色固定为蓝色，与公共学习资料（橙色）区分 */
.case-card {
  --case-accent: #1677ff;
  background: #181a20;
  border: 1px solid #2a2a2a;
  border-top: 3px solid var(--case-accent);
  border-radius: 10px;
  padding: 0 16px 14px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: hidden;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.case-card:hover {
  border-color: #4091ff;
  box-shadow: 0 4px 18px rgba(64, 145, 255, 0.16);
}
.thumb {
  position: relative;
  margin: 0 -16px 4px;
  height: 150px;
  background: #0b0d12;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.thumb-fallback {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  color: #4b5a73;
  font-size: 12px;
}
.kind-badge {
  position: absolute;
  top: 8px;
  left: 8px;
  padding: 2px 10px;
  border-radius: 10px;
  background: var(--case-accent);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
}
.count-badge {
  position: absolute;
  right: 8px;
  bottom: 8px;
  padding: 1px 8px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.65);
  color: #e5e6eb;
  font-size: 11px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.sub-tag {
  padding: 0 8px;
  border-radius: 4px;
  font-size: 11px;
  line-height: 20px;
  border: 1px solid #2f4a7a;
  color: #9ec1ff;
}
.sub-tag.is-temp {
  border-color: #3a4256;
  color: #c9cdd4;
}
.card-title {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: #e5e6eb;
}
.meta-line, .patient-line {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--hy-c-text-4, #c9cdd4);
}
.dot { color: #aeb6c2; }
.grade { font-size: 13px; font-weight: 700; color: #9ec1ff; }
.kicker {
  display: inline-block;
  margin-right: 6px;
  padding: 0 6px;
  border-radius: 4px;
  background: #1d3a6e;
  color: #d6e4ff;
  font-size: 12px;
}
.desc {
  font-size: 13px;
  color: #d5dae3;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card-actions {
  display: flex;
  gap: 8px;
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px dashed #2a2a2a;
}

.muted { color: var(--hy-c-text-3, #86909c); }
.muted.small { font-size: 11px; }

.pagination { margin-top: 16px; display: flex; justify-content: center; }
.multiline { white-space: pre-wrap; word-break: break-word; }

.detail-body { display: flex; flex-direction: column; gap: 12px; }
.detail-body .hint {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--hy-c-page, #f5f9ff);
  padding: 8px 12px;
  border-radius: 6px;
  border: 1px solid var(--hy-c-border, #e6effe);
}
.who { color: var(--hy-c-text, #1d2129); font-size: 13px; }
</style>

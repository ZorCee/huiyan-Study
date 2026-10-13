<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { adminGetNote, adminListNotes, type LearningNote } from '@/api/learning'

const loading = ref(false)
const list = ref<LearningNote[]>([])
const total = ref(0)
const query = reactive({ keyword: '', userId: undefined as number | undefined, page: 1, pageSize: 20 })

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<LearningNote | null>(null)

async function load() {
  loading.value = true
  try {
    const res = await adminListNotes({
      keyword: query.keyword.trim() || undefined,
      userId: query.userId || undefined,
      page: query.page,
      pageSize: query.pageSize
    })
    list.value = res.list
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function reset() {
  query.keyword = ''
  query.userId = undefined
  search()
}

async function openDetail(row: LearningNote) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await adminGetNote(row.id)
  } finally {
    detailLoading.value = false
  }
}

const formatTime = (t: string | null) => (t ? t.replace('T', ' ').slice(0, 16) : '-')

onMounted(load)
</script>

<template>
  <div class="admin-notes">
    <header class="page-head">
      <h1 class="page-title">笔记管理（审核视图）</h1>
      <p class="page-sub">查看全部用户的学习笔记，仅供审核使用，这里不能修改或删除笔记。</p>
    </header>

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="他人笔记 · 审核视图，访问将被记录"
      description="每次打开列表或详情，系统都会记下访问人、时间和查看了哪条笔记，可在平台管理后台的操作日志中查看。"
      class="audit-alert"
    />

    <div class="toolbar">
      <el-input
        v-model="query.keyword"
        placeholder="搜索标题 / 内容 / 标签"
        clearable
        class="kw"
        @keyup.enter="search"
      />
      <el-input-number
        v-model="query.userId"
        :min="1"
        :controls="false"
        placeholder="作者用户 ID"
        class="uid"
      />
      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="reset">重置</el-button>
    </div>

    <el-table v-loading="loading" :data="list" border stripe empty-text="没有符合条件的笔记">
      <el-table-column label="作者" width="140">
        <template #default="{ row }">
          <div class="author">
            <span class="author-name">{{ row.userName || '未知用户' }}</span>
            <span class="author-id">ID {{ row.userId }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="标题" min-width="200">
        <template #default="{ row }">{{ row.title || '（未命名笔记）' }}</template>
      </el-table-column>
      <el-table-column label="关联" min-width="180">
        <template #default="{ row }">
          <span v-if="row.caseNo">病例 {{ row.caseNo }} {{ row.caseTitle }}</span>
          <span v-else-if="row.resourceTitle">资料《{{ row.resourceTitle }}》</span>
          <span v-else class="muted">-</span>
        </template>
      </el-table-column>
      <el-table-column label="更新时间" width="160">
        <template #default="{ row }">{{ formatTime(row.updatedAt || row.createdAt) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">查看</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="query.page"
      v-model:page-size="query.pageSize"
      :total="total"
      :page-sizes="[20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      class="pager"
      @current-change="load"
      @size-change="search"
    />

    <el-dialog v-model="detailVisible" title="笔记详情（只读）" width="640px">
      <div v-loading="detailLoading" class="detail">
        <template v-if="detail">
          <div class="detail-meta">
            <el-tag type="warning" effect="plain">他人笔记</el-tag>
            <span>作者：{{ detail.userName }}（ID {{ detail.userId }}）</span>
            <span class="muted">{{ formatTime(detail.updatedAt || detail.createdAt) }}</span>
          </div>
          <h2 class="detail-title">{{ detail.title || '（未命名笔记）' }}</h2>
          <div v-if="detail.tags" class="detail-tags">
            <el-tag v-for="t in detail.tags.split(',').filter(Boolean)" :key="t" size="small">{{ t }}</el-tag>
          </div>
          <pre class="detail-content">{{ detail.content || '（无内容）' }}</pre>
        </template>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.admin-notes {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 20px 24px;
}
.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}
.page-sub {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.kw {
  width: 260px;
}
.uid {
  width: 140px;
}
.author {
  display: flex;
  flex-direction: column;
}
.author-name {
  font-weight: 500;
}
.author-id,
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.pager {
  justify-content: flex-end;
}
.detail {
  min-height: 120px;
}
.detail-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.detail-title {
  margin: 12px 0 8px;
  font-size: 17px;
}
.detail-tags {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}
.detail-content {
  margin: 0;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: inherit;
  line-height: 1.6;
}
</style>

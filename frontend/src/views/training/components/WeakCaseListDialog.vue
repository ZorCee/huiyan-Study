<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { RotationApi } from '@/api'
import type { WeakCaseItem } from '@/api/rotation'

const props = defineProps<{
  modelValue: boolean
  title?: string
  label?: string
  errorType?: 'missed' | 'false_positive' | string
  studyYear?: string
  rotationBatch?: string
  mentorGroup?: string
  userId?: number
  studentName?: string
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()

const router = useRouter()
const visible = computed({
  get: () => props.modelValue,
  set: (val) => emit('update:modelValue', val)
})

const loading = ref(false)
const list = ref<WeakCaseItem[]>([])

const typeLabel = computed(() => {
  if (props.errorType === 'missed') return '漏诊'
  if (props.errorType === 'false_positive') return '误诊'
  return '错题'
})

const typeTagType = computed(() => {
  if (props.errorType === 'missed') return 'danger'
  if (props.errorType === 'false_positive') return 'warning'
  return 'info'
})

const loadData = async () => {
  if (!props.modelValue) return
  loading.value = true
  try {
    const res = await RotationApi.getWeakDetail({
      studyYear: props.studyYear,
      rotationBatch: props.rotationBatch,
      mentorGroup: props.mentorGroup,
      userId: props.userId,
      label: props.label || '',
      errorType: props.errorType
    })
    list.value = res || []
  } catch {
    list.value = []
  } finally {
    loading.value = false
  }
}

watch(
  () => props.modelValue,
  (val) => {
    if (val) loadData()
  }
)

const openWorkstation = (item: WeakCaseItem) => {
  visible.value = false
  router.push({
    path: '/training/practice/workstation',
    query: {
      caseId: String(item.caseId),
      sessionId: String(item.sessionId),
      view: 'report'
    }
  })
}
</script>

<template>
  <el-dialog
    v-model="visible"
    :title="title || `${typeLabel}明细`"
    width="860px"
    destroy-on-close
    append-to-body
    class="weak-case-dialog"
  >
    <div class="dialog-header-info">
      <el-tag :type="typeTagType" effect="dark" class="mr8">
        {{ typeLabel }}病灶
      </el-tag>
      <span class="focus-label">{{ label || '全部常见问题' }}</span>
      <span v-if="studentName" class="meta-tag">学员：{{ studentName }}</span>
      <span v-else-if="mentorGroup" class="meta-tag">
        范围：{{ studyYear ? `${studyYear} · ` : '' }}{{ mentorGroup }}
      </span>
      <span class="count-tag">共 {{ list.length }} 条相关作答记录</span>
    </div>

    <el-table v-loading="loading" :data="list" size="small" stripe max-height="480">
      <el-table-column label="眼底图像" width="90">
        <template #default="{ row }">
          <el-image
            v-if="row.imageUrl"
            :src="row.imageUrl"
            :preview-src-list="[row.imageUrl]"
            fit="cover"
            class="case-thumb"
            preview-teleported
          />
          <span v-else class="muted">无缩略图</span>
        </template>
      </el-table-column>
      <el-table-column prop="caseNo" label="病例编号" width="120">
        <template #default="{ row }">
          <strong>{{ row.caseNo }}</strong>
        </template>
      </el-table-column>
      <el-table-column prop="caseTitle" label="病例诊断 / 标题" min-width="160" show-overflow-tooltip />
      <el-table-column prop="studentName" label="学员" width="100" />
      <el-table-column label="错误判定" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="row.errorType === 'missed' ? 'danger' : 'warning'" effect="plain">
            {{ row.errorType === 'missed' ? '漏诊' : '误诊' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="note" label="判定说明 / 错点" min-width="170" show-overflow-tooltip />
      <el-table-column label="交卷得分" width="90">
        <template #default="{ row }">
          <span :class="row.scoreTotal >= 60 ? 'text-pass' : 'text-fail'">
            {{ row.scoreTotal.toFixed(1) }} 分
          </span>
        </template>
      </el-table-column>
      <el-table-column label="交卷时间" width="140">
        <template #default="{ row }">
          {{ (row.submittedAt || '').slice(0, 16) || '—' }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openWorkstation(row)">
            查看判读
          </el-button>
        </template>
      </el-table-column>
      <template #empty>
        <div class="empty-tip">{{ loading ? '正在拉取明细…' : '暂无相关病例记录' }}</div>
      </template>
    </el-table>

    <template #footer>
      <div class="dialog-foot">
        <span class="muted text-tip">点击「查看判读」可直接打开阅片工作台查看学员标注、AI 金标准对比及逐题扣分详情。</span>
        <el-button @click="visible = false">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.dialog-header-info {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
  font-size: 13px;
}
.focus-label {
  font-size: 15px;
  font-weight: 600;
  color: #1f2329;
}
.meta-tag {
  color: #646a73;
  background: #f2f3f5;
  padding: 2px 8px;
  border-radius: 4px;
}
.count-tag {
  margin-left: auto;
  color: #8f959e;
}
.case-thumb {
  width: 54px;
  height: 54px;
  border-radius: 4px;
  border: 1px solid #dee0e3;
  display: block;
}
.text-pass {
  color: #00b42a;
  font-weight: 600;
}
.text-fail {
  color: #f53f3f;
  font-weight: 600;
}
.mr8 {
  margin-right: 4px;
}
.muted {
  color: #8f959e;
}
.empty-tip {
  padding: 30px;
  color: #8f959e;
  text-align: center;
}
.dialog-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.text-tip {
  font-size: 12px;
}
</style>

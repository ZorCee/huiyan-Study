<script setup lang="ts">
/**
 * 病例实时检索选择组件 (CaseSelect)
 * - 支持按病例 ID、编号、标题实时模糊搜索与选择
 * - 防抖处理 (250ms) + 异步请求竞态处理 (自增 RequestId 守卫)
 * - 丰富的候选项元数据呈现（检查日期、脱敏患者、影像数、病种等）
 * - 支持键盘上下键、Enter 选中与 Escape 关闭
 */
import { onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { getCaseBrowseList, getCaseBrowseDetail, type CaseBrowseItem } from '@/api/case-browse'

const props = withDefaults(
  defineProps<{
    modelValue?: number | null
    placeholder?: string
    disabled?: boolean
    clearable?: boolean
    /** 打开弹窗时传入的初始病例信息（用于直接回显） */
    initialCase?: {
      caseId?: number | null
      caseNo?: string
      caseTitle?: string
      patientName?: string
      patientGender?: string
      patientAge?: number
      examOn?: string
      imageCount?: number
    } | null
  }>(),
  {
    modelValue: null,
    placeholder: '输入病例 ID、编号或关键词实时搜索（例如输入 1）',
    disabled: false,
    clearable: true,
    initialCase: null
  }
)

const emit = defineEmits<{
  (e: 'update:modelValue', val: number | null): void
  (e: 'change', item: CaseBrowseItem | null): void
}>()

const options = ref<CaseBrowseItem[]>([])
const loading = ref(false)
const currentRequestId = ref(0)
let debounceTimer: ReturnType<typeof setTimeout> | null = null

/** 格式化已选中项在输入框内的展示文本 */
const formatLabel = (item: CaseBrowseItem) => {
  const parts = [`ID #${item.id}`]
  if (item.caseNo) parts.push(item.caseNo)
  if (item.title) parts.push(`(${item.title})`)
  return parts.join(' · ')
}

/** 异步检索病例 */
const fetchCases = async (kw: string) => {
  const reqId = ++currentRequestId.value
  loading.value = true
  try {
    const res = await getCaseBrowseList({
      keyword: kw.trim(),
      page: 1,
      pageSize: 30
    })
    // 竞态守卫：如果已有更新的请求发出，丢弃本次过期结果
    if (reqId !== currentRequestId.value) return
    options.value = res.list || []
  } catch (err: any) {
    if (reqId !== currentRequestId.value) return
    options.value = []
    ElMessage.error(err?.message || '病例检索失败，请稍后重试')
  } finally {
    if (reqId === currentRequestId.value) {
      loading.value = false
    }
  }
}

/** 供 el-select remote-method 调用的防抖检索 */
const handleRemoteSearch = (query: string) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    fetchCases(query)
  }, 250)
}

/** 选项变更处理 */
const handleChange = (val: number | null) => {
  if (!val) {
    emit('update:modelValue', null)
    emit('change', null)
    return
  }
  const found = options.value.find((it) => it.id === val) || null
  emit('update:modelValue', val)
  emit('change', found)
}

/** 清空选择 */
const handleClear = () => {
  emit('update:modelValue', null)
  emit('change', null)
  // 清空后重新拉取默认最近病例，便于重新选择
  fetchCases('')
}

/** 下拉框展开/收起事件 */
const handleVisibleChange = (visible: boolean) => {
  if (!visible) {
    // 下拉框关闭时，如果当前有选中项，确保其在 options 中以维持 label 显示
    if (props.modelValue) {
      ensureSelectedOption(props.modelValue)
    }
  } else {
    // 下拉框打开时，若当前无选项列表，预拉取候选
    if (!options.value.length) {
      fetchCases('')
    }
  }
}

/** 确保当前选中的病例存在于 options 中，以支持正常回显 */
const ensureSelectedOption = async (id: number | null) => {
  if (!id) return
  if (options.value.some((it) => it.id === id)) return

  // 优先用 initialCase 回填
  if (props.initialCase && props.initialCase.caseId === id) {
    options.value.unshift({
      id,
      caseNo: props.initialCase.caseNo || `CASE#${id}`,
      title: props.initialCase.caseTitle || '',
      description: '',
      category: 'DR',
      categoryText: '教学病例',
      difficulty: 'EASY',
      difficultyText: '入门',
      drLevel: null,
      drGradeText: '',
      archiveStatus: 'ACTIVE',
      isPublished: true,
      isTrainCase: true,
      creatorId: 0,
      creatorName: '',
      creatorRole: '',
      thumbUrl: null,
      imageCount: props.initialCase.imageCount ?? 1,
      patientName: props.initialCase.patientName || '',
      patientGender: props.initialCase.patientGender || 'U',
      patientAge: props.initialCase.patientAge || 0,
      examOn: props.initialCase.examOn || '',
      createdAt: '',
      updatedAt: null
    } as unknown as CaseBrowseItem)
    return
  }

  // 否则尝试调详情接口获取单条回显
  try {
    const detail = await getCaseBrowseDetail(id)
    if (detail && !options.value.some((it) => it.id === id)) {
      options.value.unshift(detail as unknown as CaseBrowseItem)
    }
  } catch {
    // 降级兜底占位
    options.value.unshift({
      id,
      caseNo: `病例 #${id}`,
      title: '',
      description: '',
      category: 'DR',
      categoryText: '',
      difficulty: '',
      difficultyText: '',
      drLevel: null,
      drGradeText: '',
      archiveStatus: 'ACTIVE',
      isPublished: true,
      isTrainCase: true,
      creatorId: 0,
      creatorName: '',
      creatorRole: '',
      thumbUrl: null,
      imageCount: 1,
      patientName: '',
      patientGender: 'U',
      patientAge: 0,
      examOn: '',
      createdAt: '',
      updatedAt: null
    } as unknown as CaseBrowseItem)
  }
}

watch(
  () => props.modelValue,
  (newVal) => {
    if (newVal) ensureSelectedOption(newVal)
  },
  { immediate: true }
)

watch(
  () => props.initialCase,
  (newInit) => {
    if (newInit?.caseId && props.modelValue === newInit.caseId) {
      ensureSelectedOption(newInit.caseId)
    }
  },
  { deep: true }
)

onMounted(() => {
  // 组件加载时预先拉取一次候选病例列表
  if (!options.value.length) {
    fetchCases('')
  }
})
</script>

<template>
  <div class="case-select-wrapper">
    <el-select
      :model-value="modelValue"
      filterable
      remote
      :clearable="clearable"
      :disabled="disabled"
      :placeholder="placeholder"
      :remote-method="handleRemoteSearch"
      :loading="loading"
      loading-text="正在检索病例..."
      no-data-text="未找到匹配的病例"
      teleported
      fit-input-width
      popper-class="case-select-dropdown-popper"
      class="case-select"
      @change="handleChange"
      @clear="handleClear"
      @visible-change="handleVisibleChange"
    >
      <el-option
        v-for="item in options"
        :key="item.id"
        :label="formatLabel(item)"
        :value="item.id"
        class="case-option-item"
      >
        <div class="opt-card">
          <div class="opt-header">
            <span class="opt-id-tag">ID #{{ item.id }}</span>
            <span class="opt-no">{{ item.caseNo }}</span>
            <span v-if="item.title" class="opt-title">{{ item.title }}</span>
            <el-tag v-if="item.categoryText" size="small" type="info" class="opt-cat">
              {{ item.categoryText }}
            </el-tag>
          </div>
          <div class="opt-meta">
            <span v-if="item.patientName" class="meta-field">
              👤 {{ item.patientName }}
              <template v-if="item.patientAge"> ({{ item.patientAge }}岁)</template>
            </span>
            <span v-if="item.examOn" class="meta-field">
              📅 {{ item.examOn }}
            </span>
            <span class="meta-field">
              🖼️ {{ item.imageCount ?? 1 }} 张原图
            </span>
            <span v-if="item.difficultyText" class="meta-field">
              ⭐ {{ item.difficultyText }}
            </span>
          </div>
        </div>
      </el-option>
    </el-select>
  </div>
</template>

<style scoped>
.case-select-wrapper {
  width: 100%;
}

.case-select {
  width: 100%;
}

.opt-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.opt-header {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.opt-id-tag {
  display: inline-block;
  padding: 1px 6px;
  background-color: var(--hy-c-primary-soft, #ecf5ff);
  color: #409eff;
  border: 1px solid #d9ecff;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  line-height: 16px;
}

.opt-no {
  font-weight: 600;
  color: var(--hy-c-text, #303133);
}

.opt-title {
  color: var(--hy-c-text-2, #606266);
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.opt-cat {
  margin-left: auto;
}

.opt-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 11px;
  color: var(--hy-c-text-3, #909399);
}

.meta-field {
  display: inline-flex;
  align-items: center;
}
</style>

<style>
/* 针对 teleport 到 body 下的下拉选项进行样式覆盖 */
.case-select-dropdown-popper .el-select-dropdown__item {
  height: auto !important;
  line-height: normal !important;
  padding: 8px 12px !important;
  border-bottom: 1px solid #f0f2f5;
}

.case-select-dropdown-popper .el-select-dropdown__item:last-child {
  border-bottom: none;
}
</style>

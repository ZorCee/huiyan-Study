/**
 * 教师/管理员「作业批阅」待处理数，侧栏角标与首页提示共用同一份状态。
 *
 * 统计口径（必须与「作业批阅」列表一致）：
 *   接口 ReadingApi.getReadingList（GET /reading/records）
 *   条件 status = 'SUBMITTED'，不带 caseId，取返回的 total。
 *
 * 任何会改变待审状态的操作（通过 / 驳回）成功后都应调用 refreshPendingReviewCount()。
 */
import { ref } from 'vue'
import { ReadingApi } from '@/api'

export const PENDING_REVIEW_STATUS: ReadingApi.ReadingStatus = 'SUBMITTED'

const pendingReviewCount = ref(0)
let inflight: Promise<void> | null = null

const refreshPendingReviewCount = (): Promise<void> => {
  if (inflight) return inflight
  inflight = (async () => {
    try {
      const page = await ReadingApi.getReadingList({
        status: PENDING_REVIEW_STATUS,
        page: 1,
        pageSize: 1
      })
      pendingReviewCount.value = Number(page?.total) || 0
    } catch {
      /* 保留上一次的值，避免网络抖动时角标闪烁成 0 */
    } finally {
      inflight = null
    }
  })()
  return inflight
}

/** 列表已经用同一口径查过时直接写入，免得再发一次请求。 */
const syncPendingReviewCount = (total: number) => {
  pendingReviewCount.value = Math.max(0, Number(total) || 0)
}

const resetPendingReviewCount = () => {
  pendingReviewCount.value = 0
}

export const usePendingReviewCount = () => ({
  pendingReviewCount,
  refreshPendingReviewCount,
  syncPendingReviewCount,
  resetPendingReviewCount
})

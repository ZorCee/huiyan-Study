/**
 * 正式考试。老师组卷，学员限时作答，收卷后导出成绩。
 */
import http from '@/utils/request'
import type { PracticeRecord } from './practice'

export interface ExamPaper {
  id: number
  title: string
  status: 'OPEN' | 'CLOSED' | string
  durationMinutes: number
  passScore: number
  allowBack: boolean
  pickMode: 'SELECTED' | 'DRAW' | string
  category: string
  difficulty: string
  caseIds: number[]
  questionCount: number
  caseNos: string[]
  enteredCount: number
  handedCount: number
  openedAt?: string | null
  closedAt?: string | null
  publisherName?: string
  participants?: ExamParticipant[]
  audienceScope?: string
  audienceValues?: string[]
  audienceIds?: number[]
  /** 例如「带教组：A组、B组」 */
  audienceLabel?: string
  /** 目标学员人数，只有老师能看到 */
  audienceCount?: number
  /** READY 未进入 / DOING 作答中 / HANDED 已交卷 / ABSENT 缺考 / TIMEOUT_BLANK 超时未作答（系统补交的空白卷） */
  mineStatus?: string
  /** 本人已交卷后的平均分。未交卷时为空。 */
  mineScore?: number | null
  minePassed?: boolean | null
  maxAttempts?: number
  currentRound?: number
  remainingAttempts?: number
  canRetake?: boolean
  retakeHint?: string
}

export interface ExamParticipant {
  name: string
  username?: string
  state: string
  userId?: number
}

export interface ExamCaseOption {
  id: number
  caseNo: string
  title: string
  category: string
  categoryText: string
  difficulty: string
  difficultyText: string
}

export interface ExamCreateBody {
  title: string
  durationMinutes: number
  passScore: number
  allowBack: boolean
  pickMode: 'SELECTED' | 'DRAW'
  category?: string
  difficulty?: string
  caseIds?: number[]
  questionCount?: number
  audienceScope?: ExamAudienceScope
  audienceValues?: string[]
  audienceIds?: number[]
}

export type ExamAudienceScope = 'ALL' | 'YEAR' | 'BATCH' | 'GROUP' | 'PEOPLE'

export interface ExamAudienceItem {
  value: string
  label: string
  count: number
}

export interface ExamAudienceStudent {
  id: number
  name: string
  username: string
  studyYear: string
  rotationBatch: string
  mentorGroup: string
}

export interface ExamAudienceOptions {
  total: number
  years: ExamAudienceItem[]
  batches: ExamAudienceItem[]
  groups: ExamAudienceItem[]
  students: ExamAudienceStudent[]
}

export interface ExamPreviewQuestion {
  id: string
  stem: string
  questionType: string
  typeText: string
  /** OWN 病例专属题 / GENERIC 补充的通用题 */
  source: 'OWN' | 'GENERIC' | string
}

export interface ExamPreviewCase {
  caseId: number
  caseNo: string
  title: string
  ownCount: number
  genericCount: number
  /** 从常规题库随机补齐的题数，学员进入时才抽 */
  legacyCount: number
  questions: ExamPreviewQuestion[]
}

export interface ExamPreview {
  cases: ExamPreviewCase[]
  totalQuestions: number
  ownTotal: number
  genericTotal: number
  legacyTotal: number
  typeCounts: Record<string, number>
}

const answerBody = (paperId: number, payload: Record<string, unknown>) =>
  http.post<PracticeRecord>(`/exams/${paperId}/hand-in`, payload, { showSuccess: false })

export const listExams = () => http.get<ExamPaper[]>('/exams')

export const caseOptions = () => http.get<ExamCaseOption[]>('/exams/case-options')

export const audienceOptions = () => http.get<ExamAudienceOptions>('/exams/audience-options')

export const previewExam = (caseIds: number[]) =>
  http.post<ExamPreview>('/exams/preview', { caseIds }, { showSuccess: false })

export const createExam = (body: ExamCreateBody) => http.post<ExamPaper>('/exams', body)

export const startExam = (paperId: number, options?: { retake?: boolean }) => {
  const query = options?.retake ? '?retake=true' : ''
  return http.post<PracticeRecord>(`/exams/${paperId}/start${query}`, {}, { showSuccess: false })
}

export const saveDraft = (paperId: number, payload: Record<string, unknown>) =>
  http.post<PracticeRecord>(`/exams/${paperId}/draft`, payload, { showSuccess: false })

export const handIn = answerBody

export const resetExamAttempt = (paperId: number, studentId: number) =>
  http.post<{ removed: number; message: string }>(`/exams/${paperId}/students/${studentId}/reset`)

export const collectExam = (paperId: number) =>
  http.post<{ collected: number; entered: number; message: string }>(`/exams/${paperId}/collect`)

export const downloadGrades = (paperId: number, filename: string) =>
  http.download(`/exams/${paperId}/grades`, undefined, filename)

export const removeExam = (paperId: number) => http.delete(`/exams/${paperId}`)

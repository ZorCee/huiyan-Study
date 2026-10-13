/**
 * CSU-EYES 智能诊断 API
 * 对接后端 /api/v1/diagnosis/*
 *
 * 三个入口：
 *  - MA 检测（单图）
 *  - DR 分级（双眼）
 *  - 综合诊断（单图多任务）
 *
 * 后端会自动：
 *  - 调 CSU-EYES（http://113.219.243.122:9080/api/v1/inference/...）
 *  - 创建 ScreeningCase + ScreeningResult
 *  - 落盘热力图 / 标注图到 /static/screening/
 *  - 自动生成模拟患者信息
 */

import http from '@/utils/request'

export type DiagnosisType = 'MA' | 'DR' | 'COMPREHENSIVE'
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'URGENT'
export type EyeSide = 'OD' | 'OS' | 'OU' | 'UK'

/** 上传时选填的受检者信息；刻意不含姓名、手机号、身份证号 */
export interface SubjectInfo {
  subjectCode?: string
  gender?: 'M' | 'F' | 'U'
  age?: number | null
}

const appendSubject = (fd: FormData, subject?: SubjectInfo) => {
  if (!subject) return
  const code = (subject.subjectCode || '').trim()
  if (code) fd.append('subject_code', code)
  if (subject.gender && subject.gender !== 'U') fd.append('subject_gender', subject.gender)
  if (typeof subject.age === 'number') fd.append('subject_age', String(subject.age))
}

export interface MaDiagnosisResult {
  /** null = 算法未返回 MA 字段（不是 0 个） */
  maCount: number | null
  overlayUrl: string
  heatmapUrl: string
  inferenceTime: number
}

export interface DrEyeResult {
  grade: number
  gradeName: string
  imageUrl: string
  heatmapUrl: string
}

export interface DrDiagnosisResult {
  overallGrade: number
  overallGradeName: string
  left: DrEyeResult
  right: DrEyeResult
  inferenceTime: number
}

export interface ComprehensiveDiagnosisResult {
  overallGrade: number
  maCount: number | null
  maOverlayUrl: string
  drHeatmapUrl: string
  summary: string
  inferenceTime: number
}

export interface DiagnosisOut {
  taskId: string
  caseId: number
  caseSn: string
  /** 受检者显示名：自动编号，或已脱敏的历史姓名 */
  patientName: string
  /** auto = 上传时自动生成的编号；input = 上传时录入 */
  subjectSource?: 'auto' | 'input'
  /** 录入人（上传医生） */
  submitterName?: string
  diagnosisType: DiagnosisType
  riskLevel: RiskLevel
  primaryImageUrl: string
  ma?: MaDiagnosisResult | null
  dr?: DrDiagnosisResult | null
  comprehensive?: ComprehensiveDiagnosisResult | null
  raw?: Record<string, any>
}

/* ========== 中文展示工具 ========== */

export const DIAGNOSIS_TYPE_LABEL: Record<DiagnosisType, string> = {
  MA: '微动脉瘤检测',
  DR: 'DR 分级',
  COMPREHENSIVE: '综合诊断',
}

export const DIAGNOSIS_TYPE_DESC: Record<DiagnosisType, string> = {
  MA: '检出眼底图像中的微动脉瘤位置与数量，输出标注图',
  DR: '左右眼分别评估糖尿病视网膜病变 0~4 级，输出整体分级与 GradCAM',
  COMPREHENSIVE: '同一张图同时执行 MA 检测 + DR 分级，给出综合摘要',
}

export const RISK_LABEL: Record<RiskLevel, string> = {
  LOW: '正常',
  MEDIUM: '中危',
  HIGH: '高危',
  URGENT: '紧急',
}

export const RISK_TAG_TYPE: Record<RiskLevel, 'success' | 'warning' | 'danger'> = {
  LOW: 'success',
  MEDIUM: 'warning',
  HIGH: 'danger',
  URGENT: 'danger',
}

/* ========== API ========== */

export interface UploadProgressCb {
  (percent: number): void
}

/**
 * MA 微动脉瘤检测（单张眼底图）
 */
export const diagnoseMa = (
  file: File,
  eye: EyeSide = 'UK',
  modelId?: number,
  onProgress?: UploadProgressCb,
  subject?: SubjectInfo
) => {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('eye', eye)
  if (modelId !== undefined) fd.append('model_id', String(modelId))
  appendSubject(fd, subject)
  return http.upload<DiagnosisOut>(
    '/diagnosis/ma',
    fd,
    {
      showSuccess: true,
      successText: '诊断完成',
      // 关闭通用错误弹窗，由 DiagnosisUpload.vue 做语义化处理（405 / 502 等）
      showError: false,
    },
    {
      timeout: 120_000,
      onUploadProgress: (e) => {
        if (!onProgress) return
        const total = e.total || 0
        if (total > 0) onProgress(Math.round(((e.loaded || 0) * 100) / total))
      },
    }
  )
}

/**
 * DR 双眼分级
 */
export const diagnoseDr = (
  leftEye: File,
  rightEye: File,
  modelId?: number,
  onProgress?: UploadProgressCb,
  subject?: SubjectInfo
) => {
  const fd = new FormData()
  fd.append('left_eye', leftEye)
  fd.append('right_eye', rightEye)
  if (modelId !== undefined) fd.append('model_id', String(modelId))
  appendSubject(fd, subject)
  return http.upload<DiagnosisOut>(
    '/diagnosis/dr',
    fd,
    {
      showSuccess: true,
      successText: '诊断完成',
      showError: false,
    },
    {
      timeout: 180_000,
      onUploadProgress: (e) => {
        if (!onProgress) return
        const total = e.total || 0
        if (total > 0) onProgress(Math.round(((e.loaded || 0) * 100) / total))
      },
    }
  )
}

/**
 * 综合诊断（单张眼底图，多任务并发）
 */
export const diagnoseComprehensive = (
  file: File,
  tasks?: ('ma_detection' | 'dr_grading')[],
  onProgress?: UploadProgressCb,
  subject?: SubjectInfo
) => {
  const fd = new FormData()
  fd.append('file', file)
  if (tasks && tasks.length) {
    for (const t of tasks) fd.append('tasks', t)
  }
  appendSubject(fd, subject)
  return http.upload<DiagnosisOut>(
    '/diagnosis/comprehensive',
    fd,
    {
      showSuccess: true,
      successText: '诊断完成',
      showError: false,
    },
    {
      timeout: 180_000,
      onUploadProgress: (e) => {
        if (!onProgress) return
        const total = e.total || 0
        if (total > 0) onProgress(Math.round(((e.loaded || 0) * 100) / total))
      },
    }
  )
}

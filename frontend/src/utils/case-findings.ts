/**
 * 多病种结论：病种选项与来源标签。
 * 与后端 app/services/case_findings.py 的 DISEASES 保持一致；新增病种两边各加一项。
 */

export type FindingSource = 'MANUAL' | 'DATASET' | 'AI'

export interface CaseFinding {
  disease: string
  diseaseLabel: string
  value: string
  valueLabel: string
  source: FindingSource
  aiValue?: string | null
  aiValueLabel?: string
  confirmed?: boolean
}

export interface FindingInput {
  disease: string
  /** 空字符串表示删除该病种结论 */
  value: string
}

interface DiseaseConfig {
  key: string
  label: string
  options: Array<{ value: string; label: string }>
}

export const DISEASES: DiseaseConfig[] = [
  {
    key: 'DR',
    label: '糖尿病视网膜病变',
    options: [
      { value: '0', label: '0 级 无 DR' },
      { value: '1', label: '1 级 轻度 NPDR' },
      { value: '2', label: '2 级 中度 NPDR' },
      { value: '3', label: '3 级 重度 NPDR' },
      { value: '4', label: '4 级 PDR' }
    ]
  },
  {
    key: 'GLAUCOMA',
    label: '青光眼',
    options: [
      { value: '0', label: '无' },
      { value: '1', label: '有' },
      { value: 'S', label: '疑似' }
    ]
  }
]

export const SOURCE_META: Record<FindingSource, { text: string; type: 'success' | 'primary' | 'warning' }> = {
  MANUAL: { text: '人工', type: 'success' },
  DATASET: { text: '数据集', type: 'primary' },
  AI: { text: 'AI 待复核', type: 'warning' }
}

export const optionLabel = (disease: string, value?: string | null) =>
  DISEASES.find((d) => d.key === disease)?.options.find((o) => o.value === value)?.label || ''

/** 结论与 AI 建议不一致（AI 来源本身不算冲突） */
export const hasConflict = (f?: CaseFinding | null) =>
  !!f && !!f.aiValue && f.source !== 'AI' && f.aiValue !== f.value

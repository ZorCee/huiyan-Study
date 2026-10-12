import http from '@/utils/request'

export interface BlankConfigItem {
  index: number
  key?: string
  label?: string
  expected: string
  weight?: number
}

export interface GuidelineTemplate {
  code: string
  title: string
  guideline: string
  section: string
  tags: string[]
  stem: string
  blankConfig: BlankConfigItem[]
  answer: string
  difficulty: string
  explanation: string
}

export interface QuestionItem {
  id: number
  caseId?: number | null
  imageId?: number | null
  imageUrl?: string | null
  questionType: 'IMAGE_LEVEL' | 'GUIDELINE_BLANK' | 'CHOICE' | 'SHORT_ANSWER'
  stem: string
  options?: string[] | null
  blankConfig?: BlankConfigItem[] | null
  roiBox?: Record<string, any> | [number, number, number, number] | null
  relatedAnnotationId?: string | null
  sourceGuideline?: string | null
  sourceSection?: string | null
  tags?: string[] | null
  difficulty?: string
  answer?: string
  explanation?: string
  authorName?: string
  similarityBlocked?: boolean
}

export interface QuestionCreatePayload {
  questionType: 'IMAGE_LEVEL' | 'GUIDELINE_BLANK' | 'CHOICE' | 'SHORT_ANSWER'
  caseId?: number | null
  imageId?: number | null
  imageUrl?: string | null
  stem: string
  options?: string[] | null
  answer: string
  acceptAlternatives?: any[] | null
  blankConfig?: BlankConfigItem[] | null
  roiBox?: Record<string, any> | [number, number, number, number] | null
  relatedAnnotationId?: string | null
  sourceGuideline?: string | null
  sourceSection?: string | null
  tags?: string[] | null
  difficulty?: string
  explanation?: string | null
}

export interface TemplateGeneratePayload {
  templateCode: string
  caseId?: number | null
}

export const getGuidelineTemplates = () =>
  http.get<GuidelineTemplate[]>('/question/templates')

export const generateByTemplate = (payload: TemplateGeneratePayload) =>
  http.post<QuestionItem>('/question/generate-by-template', payload)

export const createQuestion = (payload: QuestionCreatePayload) =>
  http.post<QuestionItem>('/question/create', payload)

export const getQuestionsByCase = (caseId: number, imageUrl?: string) =>
  http.get<QuestionItem[]>(`/question/by-case/${caseId}`, { imageUrl })

export const getQuestionList = (params: {
  page?: number
  pageSize?: number
  caseId?: number
  questionType?: string
  difficulty?: string
}) => http.get<{ total: number; items: QuestionItem[] }>('/question/list', params)

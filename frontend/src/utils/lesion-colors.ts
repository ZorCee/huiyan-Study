/**
 * 病灶 / 结构颜色表（IDRiD 类别）。与后端 app/services/ai_algorithm_service.py 的
 * LESION_COLORS 保持一致，回归测试 test_ai_algorithms.py 会比对两边。
 */
export interface LesionColor {
  key: string
  name: string
  color: string
}

export const LESION_COLORS: LesionColor[] = [
  { key: 'HE', name: '视网膜出血', color: '#f53f3f' },
  { key: 'EX', name: '硬性渗出', color: '#ffd700' },
  { key: 'SE', name: '软性渗出/棉绒斑', color: '#52c41a' },
  { key: 'MA', name: '微动脉瘤', color: '#eb2f96' },
  { key: 'OD', name: '视盘', color: '#1677ff' },
  { key: 'NV', name: '新生血管', color: '#13c2c2' }
]

export const lesionColor = (key: string) =>
  LESION_COLORS.find((item) => item.key === key)?.color || '#86909c'

export const lesionName = (key: string) =>
  LESION_COLORS.find((item) => item.key === key)?.name || key

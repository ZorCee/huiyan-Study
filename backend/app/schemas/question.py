"""
题库 Pydantic 传输模型
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class QuestionCreateIn(BaseModel):
    case_id: Optional[int] = Field(None, description="关联病例 ID")
    image_id: Optional[int] = Field(None, description="关联影像 ID")
    image_url: Optional[str] = Field(None, description="关联影像路径")
    question_type: str = Field("IMAGE_LEVEL", description="题型：IMAGE_LEVEL / GUIDELINE_BLANK / CHOICE")
    stem: str = Field(..., min_length=2, description="题干")
    options: Optional[List[str]] = Field(None, description="选项列表")
    answer: str = Field(..., description="标准答案")
    accept_alternatives: Optional[List[Any]] = Field(None, description="容错同义词")
    blank_config: Optional[List[Dict[str, Any]]] = Field(None, description="挖空题配置")
    related_annotation_id: Optional[str] = Field(None, description="关联病灶标注 ID")
    roi_box: Optional[Dict[str, Any]] = Field(None, description="关联 ROI 坐标框")
    source_guideline: Optional[str] = Field(None, description="临床指南全称")
    source_section: Optional[str] = Field(None, description="指南章节/条目")
    tags: Optional[List[str]] = Field(default_factory=list, description="考点标签")
    difficulty: str = Field("MEDIUM", description="难度：EASY / MEDIUM / HARD")
    explanation: str = Field("", description="解析")


class TemplateGenerateIn(BaseModel):
    template_code: str = Field(..., description="指南模板代号")
    case_id: Optional[int] = Field(None, description="绑定病例 ID")


class QuestionOut(BaseModel):
    id: int
    case_id: Optional[int] = None
    image_id: Optional[int] = None
    image_url: Optional[str] = None
    question_type: str
    stem: str
    options: Optional[List[str]] = None
    answer: Optional[str] = None # 答题前脱敏置空
    blank_config: Optional[List[Dict[str, Any]]] = None
    related_annotation_id: Optional[str] = None
    roi_box: Optional[Dict[str, Any]] = None
    source_guideline: Optional[str] = None
    source_section: Optional[str] = None
    tags: Optional[List[str]] = None
    difficulty: str
    explanation: Optional[str] = None
    created_at: Optional[str] = None

"""
眼底影像题库模型
- 支持逐图题（强绑定具体图像与病灶区域）
- 支持基于临床指南/分级标准的挖空题（带占位符与同义词容错）
"""

from typing import Optional, List, Dict, Any
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, JSON, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class QuestionTypeEnum:
    IMAGE_LEVEL = "IMAGE_LEVEL"         # 逐图题（指向具体图像病灶征象）
    GUIDELINE_BLANK = "GUIDELINE_BLANK" # 基于临床指南的挖空题
    KNOWLEDGE = "KNOWLEDGE"             # 基础知识点题
    CHOICE = "CHOICE"                   # 经典单选/多选题


class Question(Base, TimestampMixin):
    __tablename__ = "biz_question"
    __table_args__ = (
        Index("ix_question_case_image", "case_id", "image_id"),
        Index("ix_question_type", "question_type"),
        {"comment": "眼底影像题库（逐图题与指南挖空题）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False, default="IMAGE_LEVEL")
    case_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("biz_training_case.id", ondelete="CASCADE"), nullable=True, index=True
    )
    image_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)

    # 题干文本。逐图题为具体病灶描述；挖空题包含 {{blank_1}} 占位符
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    # 选择题选项列表，如 ["A. 微动脉瘤", "B. 硬性渗出", "C. 棉绒斑", "D. 视网膜前出血"]
    options: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 标准答案（主答案文本）
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # 容错同义词列表，如 ["微动脉瘤", "MA", "Microaneurysm"]
    accept_alternatives: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # 挖空题专属配置: [{"index": 1, "key": "quadrant", "label": "象限数", "expected": "2", "weight": 1.0}]
    blank_config: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # 逐图题关联的病灶矢量标注 ID（如 GOLD_1 或用户标注 ID）
    related_annotation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # 逐图题关联的 ROI 区域坐标：{"x": 120, "y": 340, "w": 60, "h": 60}
    roi_box: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 指南出处与考点元数据
    source_guideline: Mapped[Optional[str]] = mapped_column(String(128), nullable=True) # 如 "我国糖尿病视网膜病变临床诊疗指南(2022年)"
    source_section: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)   # 如 "分级标准·4-2-1原则"
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)                   # ["DR", "重度NPDR", "4-2-1原则"]
    difficulty: Mapped[str] = mapped_column(String(16), nullable=False, default="MEDIUM") # EASY/MEDIUM/HARD
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sys_user.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

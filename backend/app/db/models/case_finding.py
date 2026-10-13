# -*- coding: utf-8 -*-
"""
病例病种结论：一个病例可同时有 DR、青光眼等多个病种结论，每条带来源。

DR 结论会同步写回 biz_training_case.gold_dr_grade，评分/考试等旧逻辑不受影响。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class CaseFinding(Base, TimestampMixin):
    __tablename__ = "biz_case_finding"
    __table_args__ = (
        UniqueConstraint("case_id", "disease", name="uq_case_finding_disease"),
        {"comment": "病例病种结论（多病种 + 来源）"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("biz_training_case.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    disease: Mapped[str] = mapped_column(String(16), nullable=False, comment="DR / GLAUCOMA ...")
    value: Mapped[str] = mapped_column(String(8), nullable=False, default="", comment="结论值")
    source: Mapped[str] = mapped_column(
        String(8), nullable=False, default="AI", comment="MANUAL / DATASET / AI",
    )
    ai_value: Mapped[Optional[str]] = mapped_column(String(8), nullable=True, comment="AI 原始结论")
    confirmed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sys_user.id", ondelete="SET NULL"), nullable=True,
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

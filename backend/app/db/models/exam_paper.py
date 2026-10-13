"""老师发布的正式考试。同一套题发给学员，收卷前不公布答案。"""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class ExamPaper(Base, TimestampMixin):
    __tablename__ = "biz_exam_paper"
    __table_args__ = {"comment": "正式考试试卷"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    teacher_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sys_user.id", ondelete="RESTRICT"), nullable=False,
    )
    # OPEN 学员可进入。CLOSED 已收卷，才公布答案。
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="OPEN", index=True,
    )
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    pass_score: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    allow_back: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 最大允许考试次数（默认 2 次：1 次首考 + 1 次重考）
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    # 重考成绩聚合策略：BEST 各轮取最高分；LATEST 取最近一次
    retake_policy: Mapped[str] = mapped_column(String(16), nullable=False, default="BEST")
    # SELECTED 老师点名病例。DRAW 按病种和难度抽出一套，全班同一套。
    pick_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="SELECTED")
    category: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    difficulty: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    case_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # 受考对象。ALL 全体学员；YEAR/BATCH/GROUP 按 sys_user 上的年级、轮转批次、带教组，
    # audience_values 可多选；PEOPLE 指定学员，存在 audience_ids。历史考试为 ALL。
    audience_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="ALL")
    audience_values: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    audience_ids: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

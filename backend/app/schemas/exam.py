"""老师组卷、学员进入、收卷后的成绩表。"""

from datetime import datetime
from typing import List, Optional

from pydantic import Field

from app.schemas.practice import PracticeSubmitParams, _CamelModel


class ExamCreate(_CamelModel):
    title: str = Field(..., min_length=1, max_length=64)
    duration_minutes: int = Field(60, ge=1, le=240)
    pass_score: int = Field(60, ge=0, le=100)
    allow_back: bool = False
    # SELECTED 指定病例；DRAW 按病种、难度抽一套，全班相同。
    pick_mode: str = "SELECTED"
    category: str = ""
    difficulty: str = ""
    case_ids: List[int] = Field(default_factory=list)
    question_count: int = Field(3, ge=1, le=20)
    # ALL / YEAR / BATCH / GROUP / PEOPLE
    audience_scope: str = "ALL"
    audience_values: List[str] = Field(default_factory=list)
    audience_ids: List[int] = Field(default_factory=list)


class ExamAudienceItem(_CamelModel):
    value: str
    label: str
    count: int = 0


class ExamAudienceStudent(_CamelModel):
    id: int
    name: str
    username: str = ""
    study_year: str = ""
    rotation_batch: str = ""
    mentor_group: str = ""


class ExamAudienceOptions(_CamelModel):
    total: int = 0
    years: List[ExamAudienceItem] = Field(default_factory=list)
    batches: List[ExamAudienceItem] = Field(default_factory=list)
    groups: List[ExamAudienceItem] = Field(default_factory=list)
    students: List[ExamAudienceStudent] = Field(default_factory=list)


class ExamPreviewParams(_CamelModel):
    case_ids: List[int] = Field(default_factory=list)


class ExamPreviewQuestion(_CamelModel):
    id: str
    stem: str
    question_type: str
    type_text: str
    # OWN 病例专属题 / GENERIC 题库通用题 / LEGACY 常规题（学员进入时随机抽）
    source: str


class ExamPreviewCase(_CamelModel):
    case_id: int
    case_no: str = ""
    title: str = ""
    own_count: int = 0
    generic_count: int = 0
    legacy_count: int = 0
    questions: List[ExamPreviewQuestion] = Field(default_factory=list)


class ExamPreviewOut(_CamelModel):
    cases: List[ExamPreviewCase] = Field(default_factory=list)
    total_questions: int = 0
    own_total: int = 0
    generic_total: int = 0
    legacy_total: int = 0
    type_counts: dict = Field(default_factory=dict)


class ExamCaseOption(_CamelModel):
    id: int
    case_no: str
    title: str = ""
    category: str = ""
    category_text: str = ""
    difficulty: str = ""
    difficulty_text: str = ""


class ExamParticipant(_CamelModel):
    """已进入这场考试的学员。只返回给老师和管理员。"""
    name: str
    username: str = ""
    state: str = ""
    user_id: int = 0


class ExamPaperOut(_CamelModel):
    id: int
    title: str
    status: str
    duration_minutes: int
    pass_score: int
    allow_back: bool
    pick_mode: str
    category: str = ""
    difficulty: str = ""
    case_ids: List[int] = Field(default_factory=list)
    question_count: int = 0
    case_nos: List[str] = Field(default_factory=list)
    entered_count: int = 0
    handed_count: int = 0
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    publisher_name: str = ""
    participants: List[ExamParticipant] = Field(default_factory=list)
    audience_scope: str = "ALL"
    audience_values: List[str] = Field(default_factory=list)
    audience_ids: List[int] = Field(default_factory=list)
    audience_label: str = "全体学员"
    audience_count: int = 0
    # 学员侧：READY 未进入 / DOING 作答中 / HANDED 已交卷 / ABSENT 缺考
    # / TIMEOUT_BLANK 没有自己交卷、到时被系统补交的空白卷
    mine_status: str = ""
    # 本人已交卷后的平均分。未交卷、未参加时为空，不把别人的分数带出来。
    mine_score: Optional[float] = None
    mine_passed: Optional[bool] = None
    # 重考能力扩展
    max_attempts: int = 2
    current_round: int = 1
    remaining_attempts: int = 1
    can_retake: bool = False
    retake_hint: str = ""


class ExamHandIn(_CamelModel):
    """交卷或时间到时，带上当前这一题的作答。"""
    session_id: int
    student_dr_grade: str = ""
    student_diagnosis: str = ""
    diagnosis: dict = Field(default_factory=dict)
    annotations: list = Field(default_factory=list)
    measurements: list = Field(default_factory=list)
    text_answers: list = Field(default_factory=list)
    viewport: Optional[dict] = None
    duration_seconds: int = 0


def hand_in_as_submit(body: ExamHandIn) -> PracticeSubmitParams:
    return PracticeSubmitParams(
        session_id=body.session_id,
        student_dr_grade=body.student_dr_grade or "",
        student_diagnosis=body.student_diagnosis or "",
        diagnosis=body.diagnosis or {},
        annotations=body.annotations or [],
        measurements=body.measurements or [],
        text_answers=body.text_answers or [],
        viewport=body.viewport,
        duration_seconds=body.duration_seconds or 0,
        request_id="",
    )

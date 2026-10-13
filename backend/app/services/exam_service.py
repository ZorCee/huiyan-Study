"""老师组卷的正式考试。

抽题在发布时定稿，全班同一套。收卷前不公布答案。
学员自行开考的旧卷不走这里。
"""

import csv
import io
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.db.models import (
    CaseArchiveStatusEnum,
    ExamPaper,
    Notice,
    PracticeSession,
    PracticeStatusEnum,
    Role,
    RoleEnum,
    TrainingCase,
    User,
)
from app.schemas.exam import ExamCreate, ExamPaperOut, ExamParticipant, hand_in_as_submit
from app.schemas.practice import ExamNavItem, PracticeAnnotation, PracticeSubmitParams
from app.services.practice_service import (
    CATEGORY_TEXT,
    DIFFICULTY_TEXT,
    PracticeService,
    _is_teacher_or_admin,
    _pick_across_grades,
    _to_out,
)


def _require_teacher(user: User) -> None:
    if not _is_teacher_or_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="只有老师可以安排考试")


def _person_name(user: Optional[User]) -> str:
    if user is None:
        return ""
    return (user.real_name or "").strip() or (user.username or "").strip()


def _announce(
    db: Session,
    publisher: User,
    *,
    title: str,
    summary: str,
    content: str,
    roles: str,
    pinned: bool,
) -> None:
    """写入学员或教师能在「通知」里看到的已发布公告。"""
    from app.schemas.common import NoticeSaveParams
    from app.services.notice_service import NoticeService

    NoticeService.create(
        db,
        publisher,
        NoticeSaveParams(
            title=title[:128],
            summary=summary[:255],
            content=content,
            notice_type="EXAM",
            status="PUBLISHED",
            visible_roles=roles,
            is_top=pinned,
        ),
    )


def announce_exam_published(db: Session, teacher: User, paper: ExamPaper) -> None:
    """发布正式考试或阶段测验时通知全体学员。同一场只发一次。"""
    marker = f"考试编号：{paper.id}"
    exists = (
        db.query(Notice.id)
        .filter(Notice.notice_type == "EXAM", Notice.content.like(f"%{marker}%"))
        .first()
    )
    if exists:
        return
    name = _person_name(teacher) or "老师"
    count = len(paper.case_ids or [])
    label = audience_label(db, paper)
    scoped = (paper.audience_scope or "ALL").upper() != "ALL"
    title = f"正式考试：{paper.title}" + (f"（{label}）" if scoped else "")
    summary = f"{name} 发起了「{paper.title}」，共 {count} 题，限时 {paper.duration_minutes} 分钟。"
    if scoped:
        summary += f"受考对象：{label}。"
    content = (
        f"{name} 发起了正式考试「{paper.title}」。\n"
        f"受考对象：{label}。不在范围内的学员在考试列表里看不到这场考试。\n"
        f"共 {count} 题，限时 {paper.duration_minutes} 分钟，合格线 {paper.pass_score} 分。\n"
        "请从「今日学习」或「病例学习」进入作答。\n"
        f"{marker}"
    )
    _announce(
        db,
        teacher,
        title=title,
        summary=summary,
        content=content,
        roles="STUDENT",
        pinned=True,
    )


def notify_exam_handed(db: Session, student: User, paper: ExamPaper) -> None:
    """学员交完卷后，通知老师和管理员是谁交的。"""
    rows = _sessions(db, paper.id, student.id)
    if not rows:
        return
    round_no = max((getattr(r, "attempt_round", 1) or 1) for r in rows)
    latest_rows = [r for r in rows if (getattr(r, "attempt_round", 1) or 1) == round_no]
    if any(row.status == PracticeStatusEnum.DRAFT.value for row in latest_rows):
        return
    marker = f"交卷记录：{paper.id}-{student.id}-r{round_no}"
    exists = db.query(Notice.id).filter(Notice.content.like(f"%{marker}%")).first()
    if exists:
        return
    name = _person_name(student) or "学员"
    round_text = f"（第{round_no}次作答）" if round_no > 1 else ""
    title = f"{name} 已交卷：{paper.title}{round_text}"
    summary = f"{name}（{student.username}）已完成正式考试「{paper.title}」{round_text}。"
    content = f"{summary}\n{marker}"
    _announce(
        db,
        student,
        title=title,
        summary=summary,
        content=content,
        roles="TEACHER,ADMIN",
        pinned=False,
    )


def _paper_or_404(db: Session, paper_id: int) -> ExamPaper:
    paper = db.query(ExamPaper).filter(ExamPaper.id == paper_id).first()
    if paper is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="考试不存在")
    return paper


def _pool(db: Session) -> List[TrainingCase]:
    from app.services import case_quality
    q = db.query(TrainingCase).filter(
        TrainingCase.is_published == True,  # noqa: E712
        TrainingCase.is_train_case == True,  # noqa: E712
        TrainingCase.archive_status == CaseArchiveStatusEnum.ACTIVE.value,
    )
    return (
        case_quality.exclude_low_quality(q)
        .order_by(TrainingCase.id.asc())
        .all()
    )


AUDIENCE_SCOPES = ("ALL", "YEAR", "BATCH", "GROUP", "PEOPLE")
AUDIENCE_LABELS = {"YEAR": "年级", "BATCH": "轮转批次", "GROUP": "带教组", "PEOPLE": "指定学员"}


def _audience_field(scope: str):
    return {
        "YEAR": "study_year",
        "BATCH": "rotation_batch",
        "GROUP": "mentor_group",
    }.get(scope, "")


def _active_students(db: Session) -> List[User]:
    return (
        db.query(User)
        .join(Role, User.role_id == Role.id)
        .filter(Role.code == RoleEnum.STUDENT.value, User.is_active == True)  # noqa: E712
        .order_by(User.id.asc())
        .all()
    )


def _scope_reaches(scope: str, values: list, ids: list, user: User) -> bool:
    scope = (scope or "ALL").upper()
    if scope == "ALL":
        return True
    if scope == "PEOPLE":
        return int(user.id) in {int(item) for item in ids or []}
    field = _audience_field(scope)
    if not field:
        return False
    own = (getattr(user, field, "") or "").strip()
    return bool(own) and own in {str(item).strip() for item in values or []}


def paper_reaches(paper: ExamPaper, user: User) -> bool:
    """这名学员是不是这场考试的受考对象。老师、管理员不受限制。"""
    if _is_teacher_or_admin(user):
        return True
    return _scope_reaches(
        getattr(paper, "audience_scope", None) or "ALL",
        getattr(paper, "audience_values", None) or [],
        getattr(paper, "audience_ids", None) or [],
        user,
    )


def audience_students(db: Session, paper: ExamPaper) -> List[User]:
    return [student for student in _active_students(db) if paper_reaches(paper, student)]


def _normalize_audience(db: Session, params: ExamCreate) -> tuple:
    """校验受考对象，返回 (scope, values, ids, 目标学员)。一个学员都没有就拒绝发布。"""
    scope = (params.audience_scope or "ALL").strip().upper()
    if scope not in AUDIENCE_SCOPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="受考对象不正确")
    students = _active_students(db)
    values: list = []
    ids: list = []
    if scope == "PEOPLE":
        for raw in params.audience_ids or []:
            number = int(raw)
            if number not in ids:
                ids.append(number)
        if not ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请选择受考学员")
        known = {student.id for student in students}
        if not set(ids) <= known:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="只能选择在用的学员账号")
    elif scope != "ALL":
        for raw in params.audience_values or []:
            text = str(raw or "").strip()[:32]
            if text and text not in values:
                values.append(text)
        if not values:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"请选择{AUDIENCE_LABELS[scope]}",
            )
    targets = [student for student in students if _scope_reaches(scope, values, ids, student)]
    if not targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="所选受考对象里没有在用的学员，请先在「班级学生」里填写分组或换一个对象",
        )
    return scope, values, ids, targets


def audience_label(db: Session, paper: ExamPaper) -> str:
    scope = (getattr(paper, "audience_scope", None) or "ALL").upper()
    if scope == "ALL":
        return "全体学员"
    if scope == "PEOPLE":
        ids = [int(item) for item in (paper.audience_ids or [])]
        rows = db.query(User).filter(User.id.in_(ids)).all() if ids else []
        names = {row.id: _person_name(row) or str(row.id) for row in rows}
        shown = [names.get(item, str(item)) for item in ids[:3]]
        more = f" 等 {len(ids)} 人" if len(ids) > 3 else ""
        return f"指定学员：{'、'.join(shown)}{more}"
    return f"{AUDIENCE_LABELS.get(scope, scope)}：{'、'.join(paper.audience_values or [])}"


def _sessions(db: Session, paper_id: int, user_id: Optional[int] = None) -> List[PracticeSession]:
    query = db.query(PracticeSession).filter(PracticeSession.exam_paper_id == paper_id)
    if user_id is not None:
        query = query.filter(PracticeSession.user_id == user_id)
    return query.order_by(PracticeSession.exam_index.asc(), PracticeSession.id.asc()).all()


def _started_at(rows: List[PracticeSession]) -> Optional[datetime]:
    times = [row.started_at for row in rows if row.started_at]
    return min(times) if times else None


def seconds_left(paper: ExamPaper, rows: List[PracticeSession], now: Optional[datetime] = None) -> int:
    if paper.status == "CLOSED":
        return 0
    start = _started_at(rows)
    if start is None:
        return -1
    deadline = start + timedelta(minutes=int(paper.duration_minutes or 0))
    return max(0, int((deadline - (now or datetime.now())).total_seconds()))


def clock_expired(db: Session, record: PracticeSession, now: Optional[datetime] = None) -> bool:
    paper_id = int(record.exam_paper_id or 0)
    if not paper_id:
        return False
    paper = db.query(ExamPaper).filter(ExamPaper.id == paper_id).first()
    if paper is None or paper.status == "CLOSED":
        return False
    round_no = getattr(record, "attempt_round", 1) or 1
    all_rows = _sessions(db, paper.id, record.user_id)
    rows = [r for r in all_rows if (getattr(r, "attempt_round", 1) or 1) == round_no]
    left = seconds_left(paper, rows, now)
    return left == 0 and _started_at(rows) is not None


def paper_face(db: Session, record: PracticeSession) -> dict:
    """给练习详情附上这场考试的限时、能否回上一题、题目导航。"""
    blank = {
        "exam_paper_id": 0,
        "exam_title": "",
        "allow_back": False,
        "exam_seconds_left": -1,
        "paper_closed": False,
        "exam_pass_score": 0,
        "prev_session_id": 0,
        "prev_case_id": 0,
        "exam_items": [],
    }
    paper_id = int(getattr(record, "exam_paper_id", 0) or 0)
    if not paper_id:
        return blank
    paper = db.query(ExamPaper).filter(ExamPaper.id == paper_id).first()
    if paper is None:
        return blank
    round_no = getattr(record, "attempt_round", 1) or 1
    all_rows = _sessions(db, paper.id, record.user_id)
    rows = [r for r in all_rows if (getattr(r, "attempt_round", 1) or 1) == round_no]
    prev = next((row for row in rows if row.exam_index == (record.exam_index or 0) - 1), None)
    allow = bool(paper.allow_back)
    return {
        "exam_paper_id": paper.id,
        "exam_title": paper.title or "",
        "allow_back": allow,
        "exam_seconds_left": seconds_left(paper, rows),
        "paper_closed": paper.status == "CLOSED",
        "exam_pass_score": int(paper.pass_score or 0),
        "prev_session_id": int(prev.id) if allow and prev else 0,
        "prev_case_id": int(prev.case_id) if allow and prev else 0,
        "exam_items": [
            ExamNavItem(
                index=row.exam_index or 0,
                session_id=row.id,
                case_id=row.case_id,
                status=row.status or "",
            )
            for row in rows
        ],
    }


def answers_locked_by_paper(db: Session, record: PracticeSession) -> bool:
    paper_id = int(getattr(record, "exam_paper_id", 0) or 0)
    if not paper_id:
        return False
    paper = db.query(ExamPaper).filter(ExamPaper.id == paper_id).first()
    return paper is None or paper.status != "CLOSED"


def guard_back(db: Session, record: PracticeSession) -> None:
    paper_id = int(record.exam_paper_id or 0)
    if not paper_id:
        return
    paper = db.query(ExamPaper).filter(ExamPaper.id == paper_id).first()
    if paper is None or paper.allow_back or paper.status == "CLOSED":
        return
    round_no = getattr(record, "attempt_round", 1) or 1
    all_rows = _sessions(db, paper.id, record.user_id)
    drafts = [
        row for row in all_rows
        if (getattr(row, "attempt_round", 1) or 1) == round_no and row.status == PracticeStatusEnum.DRAFT.value
    ]
    if drafts and record.id != drafts[0].id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="这场考试不能返回上一题",
        )


def apply_draft(db: Session, record: PracticeSession, params: PracticeSubmitParams) -> None:
    record.student_dr_grade = params.student_dr_grade or ""
    record.student_diagnosis = params.student_diagnosis or ""
    record.student_diagnosis_form = params.diagnosis or None
    record.student_annotations = [item.model_dump(by_alias=False) for item in params.annotations]
    record.student_measurements = [item.model_dump(by_alias=False) for item in params.measurements]
    record.viewport_snapshot = params.viewport
    record.text_answers = [
        {"id": row.id, "value": row.value or ""}
        for row in params.text_answers
    ]
    if params.duration_seconds:
        record.duration_seconds = params.duration_seconds
    db.flush()


HAND_IN_REASONS = ("MANUAL", "TIMEOUT", "COLLECT")


def _row_blank(row: PracticeSession) -> bool:
    """这一题学员什么都没填。"""
    if (row.student_dr_grade or "").strip() or (row.student_diagnosis or "").strip():
        return False
    form = row.student_diagnosis_form
    if isinstance(form, dict) and any(value not in (None, "", [], {}) for value in form.values()):
        return False
    if row.student_annotations or row.student_measurements:
        return False
    for item in row.text_answers or []:
        if isinstance(item, dict) and str(item.get("value") or "").strip():
            return False
    return True


def is_blank_auto_hand_in(rows: List[PracticeSession]) -> bool:
    """整卷都已交，但没有一题是学员自己交的，并且每题都是空的。

    这是「进来看了一眼就走，到点被系统补交」的白卷，不能算学员考完。
    旧记录没有交卷原因（''），只要整卷全空也按此判断。
    """
    if not rows:
        return False
    if any(row.status == PracticeStatusEnum.DRAFT.value for row in rows):
        return False
    if any((row.hand_in_reason or "") == "MANUAL" for row in rows):
        return False
    return all(_row_blank(row) for row in rows)


def finalize_user(db: Session, user_id: int, paper_id: int, reason: str = "MANUAL") -> int:
    """把这名学员还没交的题按已保存的内容评分。返回补交题数。

    reason 记到每道补交题的 hand_in_reason，用来区分学员交卷和系统补交。
    """
    if reason not in HAND_IN_REASONS:
        raise ValueError(f"unknown hand-in reason: {reason}")
    rows = [
        row for row in _sessions(db, paper_id, user_id)
        if row.status == PracticeStatusEnum.DRAFT.value
    ]
    owner = db.query(User).filter(User.id == user_id).first()
    if owner is None:
        return 0
    count = 0
    for row in rows:
        saved = PracticeSubmitParams(
            session_id=row.id,
            student_dr_grade=row.student_dr_grade or "",
            student_diagnosis=row.student_diagnosis or "",
            diagnosis=row.student_diagnosis_form or {},
            annotations=[
                PracticeAnnotation.model_validate(item)
                for item in (row.student_annotations or [])
                if isinstance(item, dict)
            ],
            measurements=[
                PracticeAnnotation.model_validate(item)
                for item in (row.student_measurements or [])
                if isinstance(item, dict)
            ],
            text_answers=row.text_answers or [],
            viewport=row.viewport_snapshot,
            duration_seconds=row.duration_seconds or 0,
            request_id=f"close-{paper_id}-{row.id}",
        )
        PracticeService.submit(db, owner, saved, _clock=False)
        row.hand_in_reason = reason
        db.commit()
        count += 1
    return count


def expire_if_needed(db: Session, record: PracticeSession) -> None:
    if record.status != PracticeStatusEnum.DRAFT.value:
        return
    if not clock_expired(db, record):
        return
    paper_id = int(record.exam_paper_id or 0)
    finalize_user(db, record.user_id, paper_id, reason="TIMEOUT")
    paper = db.query(ExamPaper).filter(ExamPaper.id == paper_id).first()
    student = db.query(User).filter(User.id == record.user_id).first()
    if paper is not None and student is not None:
        notify_exam_handed(db, student, paper)


class ExamService:
    @staticmethod
    def case_options(db: Session, user: User) -> list:
        _require_teacher(user)
        from app.schemas.exam import ExamCaseOption
        return [
            ExamCaseOption(
                id=case.id,
                case_no=case.case_no,
                title=case.title or "",
                category=case.category or "",
                category_text=CATEGORY_TEXT.get(case.category, case.category or ""),
                difficulty=case.difficulty or "",
                difficulty_text=DIFFICULTY_TEXT.get(case.difficulty, case.difficulty or ""),
            )
            for case in _pool(db)
        ]

    @staticmethod
    def audience_options(db: Session, user: User):
        """发布考试时可选的年级、轮转批次、带教组和学员，带人数。"""
        _require_teacher(user)
        from app.schemas.exam import ExamAudienceItem, ExamAudienceOptions, ExamAudienceStudent

        students = _active_students(db)

        def bucket(field: str) -> list:
            counts: dict = {}
            for student in students:
                value = (getattr(student, field, "") or "").strip()
                if value:
                    counts[value] = counts.get(value, 0) + 1
            return [
                ExamAudienceItem(value=value, label=value, count=count)
                for value, count in sorted(counts.items())
            ]

        return ExamAudienceOptions(
            total=len(students),
            years=bucket("study_year"),
            batches=bucket("rotation_batch"),
            groups=bucket("mentor_group"),
            students=[
                ExamAudienceStudent(
                    id=student.id,
                    name=_person_name(student) or f"学员{student.id}",
                    username=student.username or "",
                    study_year=student.study_year or "",
                    rotation_batch=student.rotation_batch or "",
                    mentor_group=student.mentor_group or "",
                )
                for student in students
            ],
        )

    @staticmethod
    def preview(db: Session, user: User, case_ids: List[int]):
        """按学员进入考试时的同一套规则，列出每个病例会出哪些文字题。"""
        _require_teacher(user)
        from app.schemas.exam import ExamPreviewCase, ExamPreviewOut, ExamPreviewQuestion
        from app.services.question_service import QuestionService
        from app.services.practice_service import TEXT_PAPER_SIZE

        type_text = {
            "IMAGE_LEVEL": "逐图题",
            "GUIDELINE_BLANK": "指南挖空题",
            "KNOWLEDGE": "知识点题",
            "CHOICE": "选择题",
        }
        ids: list = []
        for raw in case_ids or []:
            number = int(raw)
            if number not in ids:
                ids.append(number)
        if len(ids) > 20:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="一场考试最多 20 题")
        cases = db.query(TrainingCase).filter(TrainingCase.id.in_(ids)).all() if ids else []
        by_id = {case.id: case for case in cases}
        out = ExamPreviewOut()
        for case_id in ids:
            case = by_id.get(case_id)
            if case is None:
                continue
            own, generics = QuestionService.plan_for_case(db, case_id, TEXT_PAPER_SIZE)
            legacy = max(0, TEXT_PAPER_SIZE - len(own) - len(generics))
            questions = [
                ExamPreviewQuestion(
                    id=str(q.id),
                    stem=(q.stem or "")[:200],
                    question_type=q.question_type or "",
                    type_text=type_text.get(q.question_type, q.question_type or ""),
                    source=source,
                )
                for source, group in (("OWN", own), ("GENERIC", generics))
                for q in group
            ]
            for item in questions:
                out.type_counts[item.type_text] = out.type_counts.get(item.type_text, 0) + 1
            if legacy:
                out.type_counts["常规题（随机）"] = out.type_counts.get("常规题（随机）", 0) + legacy
            out.cases.append(ExamPreviewCase(
                case_id=case.id,
                case_no=case.case_no or "",
                title=case.title or "",
                own_count=len(own),
                generic_count=len(generics),
                legacy_count=legacy,
                questions=questions,
            ))
            out.own_total += len(own)
            out.generic_total += len(generics)
            out.legacy_total += legacy
        out.total_questions = out.own_total + out.generic_total + out.legacy_total
        return out

    @staticmethod
    def create(db: Session, user: User, params: ExamCreate) -> ExamPaperOut:
        _require_teacher(user)
        title = (params.title or "").strip()
        if not title:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请填写考试名称")
        mode = (params.pick_mode or "SELECTED").upper()
        if mode not in ("SELECTED", "DRAW"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="抽题方式不正确")
        pool = {case.id: case for case in _pool(db)}
        if mode == "SELECTED":
            ids = []
            for raw in params.case_ids:
                case_id = int(raw)
                if case_id in ids:
                    continue
                if case_id not in pool:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="有病例还没加入实训，不能放进考试",
                    )
                ids.append(case_id)
            if not ids:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请至少选择一份病例")
            if len(ids) > 20:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="一场考试最多 20 题")
        else:
            matched = list(pool.values())
            category = (params.category or "").strip()
            difficulty = (params.difficulty or "").strip()
            if category:
                from app.services import case_findings

                with_disease = case_findings.case_ids_with_disease(db, category)
                matched = [
                    case for case in matched
                    if case_findings.has_disease(case, category, with_disease)
                ]
            if difficulty:
                matched = [case for case in matched if case.difficulty == difficulty]
            want = int(params.question_count or 0)
            if len(matched) < want:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"符合条件的病例只有 {len(matched)} 份，不够抽出 {want} 题",
                )
            if category or difficulty:
                from random import shuffle
                shuffle(matched)
                picked = matched[:want]
            else:
                picked = _pick_across_grades(matched, want)
            ids = [case.id for case in picked]
        scope, audience_values, audience_ids, _targets = _normalize_audience(db, params)
        paper = ExamPaper(
            audience_scope=scope,
            audience_values=audience_values,
            audience_ids=audience_ids,
            title=title,
            teacher_id=user.id,
            status="OPEN",
            duration_minutes=int(params.duration_minutes),
            pass_score=int(params.pass_score),
            allow_back=bool(params.allow_back),
            pick_mode=mode,
            category=(params.category or "").strip(),
            difficulty=(params.difficulty or "").strip(),
            case_ids=ids,
            opened_at=datetime.now(),
        )
        db.add(paper)
        db.commit()
        db.refresh(paper)
        announce_exam_published(db, user, paper)
        return ExamService._out(db, paper, user)

    @staticmethod
    def list_papers(db: Session, user: User) -> List[ExamPaperOut]:
        rows = db.query(ExamPaper).order_by(ExamPaper.id.desc()).all()
        if _is_teacher_or_admin(user):
            return [ExamService._out(db, row, user) for row in rows]
        visible = []
        for row in rows:
            mine = _sessions(db, row.id, user.id)
            if mine or (row.status == "OPEN" and paper_reaches(row, user)):
                visible.append(ExamService._out(db, row, user))
        return visible

    @staticmethod
    def _out(db: Session, paper: ExamPaper, user: User) -> ExamPaperOut:
        ids = [int(item) for item in (paper.case_ids or [])]
        cases = db.query(TrainingCase).filter(TrainingCase.id.in_(ids)).all() if ids else []
        by_id = {case.id: case.case_no for case in cases}
        people = _sessions(db, paper.id)
        by_user: dict = {}
        for row in people:
            by_user.setdefault(row.user_id, []).append(row)
        handed = sum(
            1 for rows in by_user.values()
            if rows and any(
                all(row.status != PracticeStatusEnum.DRAFT.value for row in r_rows)
                for r_rows in [
                    [r for r in rows if (getattr(r, "attempt_round", 1) or 1) == rnd]
                    for rnd in {getattr(r, "attempt_round", 1) or 1 for r in rows}
                ]
            )
        )
        mine_rows = by_user.get(user.id, [])
        max_attempts = int(getattr(paper, "max_attempts", 2) or 2)
        retake_policy = getattr(paper, "retake_policy", "BEST") or "BEST"

        rounds_map = {}
        for row in mine_rows:
            rnd = getattr(row, "attempt_round", 1) or 1
            rounds_map.setdefault(rnd, []).append(row)

        completed_rounds = [
            rnd for rnd, r_rows in rounds_map.items()
            if all(row.status != PracticeStatusEnum.DRAFT.value for row in r_rows)
        ]

        latest_round = max(rounds_map.keys()) if rounds_map else 1
        latest_rows = rounds_map.get(latest_round, [])

        if not mine_rows:
            mine = "ABSENT" if paper.status == "CLOSED" else "READY"
            current_round = 1
            remaining_attempts = max_attempts
            can_retake = False
            retake_hint = ""
        elif any(row.status == PracticeStatusEnum.DRAFT.value for row in latest_rows):
            mine = "DOING"
            current_round = latest_round
            remaining_attempts = max(0, max_attempts - latest_round)
            can_retake = False
            retake_hint = "当前轮次正在作答中"
        elif is_blank_auto_hand_in(latest_rows):
            mine = "TIMEOUT_BLANK"
            current_round = latest_round
            remaining_attempts = max(0, max_attempts - len(completed_rounds))
            if paper.status == "OPEN" and remaining_attempts > 0:
                can_retake = True
                retake_hint = f"超时未作答，可重新考试（剩余 {remaining_attempts} 次机会）"
            elif paper.status == "CLOSED":
                can_retake = False
                retake_hint = "考试已收卷，不可重考"
            else:
                can_retake = False
                retake_hint = f"已达作答上限（最多 {max_attempts} 次）"
        else:
            mine = "HANDED"
            current_round = latest_round
            remaining_attempts = max(0, max_attempts - len(completed_rounds))
            if paper.status == "OPEN" and remaining_attempts > 0:
                can_retake = True
                retake_hint = f"已交卷，可重新作答（剩余 {remaining_attempts} 次机会）"
            elif paper.status == "CLOSED":
                can_retake = False
                retake_hint = "考试已收卷，等老师公布最终结果"
            else:
                can_retake = False
                retake_hint = f"已达重考上限（最多作答 {max_attempts} 次）"

        mine_score = None
        mine_passed = None
        if completed_rounds:
            round_scores = {}
            for rnd in completed_rounds:
                nums = [
                    round(float(row.score_total or 0), 2)
                    for row in rounds_map[rnd]
                    if row.status != PracticeStatusEnum.DRAFT.value
                ]
                if nums:
                    round_scores[rnd] = round(sum(nums) / len(nums), 2)
            if round_scores:
                if retake_policy == "BEST":
                    mine_score = max(round_scores.values())
                else:
                    mine_score = round_scores[max(round_scores.keys())]
                mine_passed = mine_score >= int(paper.pass_score or 0)

        teacher = (
            db.query(User).filter(User.id == paper.teacher_id).first()
            if paper.teacher_id else None
        )
        participants: list = []
        if _is_teacher_or_admin(user) and by_user:
            people = db.query(User).filter(User.id.in_(list(by_user.keys()))).all()
            named = {person.id: person for person in people}
            for user_id, rows in by_user.items():
                person = named.get(user_id)
                round_no = max((getattr(r, "attempt_round", 1) or 1) for r in rows)
                latest_p_rows = [r for r in rows if (getattr(r, "attempt_round", 1) or 1) == round_no]
                done = bool(latest_p_rows) and all(
                    row.status != PracticeStatusEnum.DRAFT.value for row in latest_p_rows
                )
                if not done:
                    state = f"第{round_no}次作答中" if round_no > 1 else "作答中"
                elif is_blank_auto_hand_in(latest_p_rows):
                    state = "超时未作答"
                else:
                    state = f"已交卷(第{round_no}次)" if round_no > 1 else "已交卷"
                participants.append(ExamParticipant(
                    name=_person_name(person) or f"学员{user_id}",
                    username=person.username if person else "",
                    state=state,
                    user_id=user_id,
                ))
            participants.sort(key=lambda item: (not item.state.startswith("已交卷"), item.name))
        return ExamPaperOut(
            id=paper.id,
            title=paper.title,
            status=paper.status,
            duration_minutes=paper.duration_minutes,
            pass_score=paper.pass_score,
            allow_back=bool(paper.allow_back),
            pick_mode=paper.pick_mode,
            category=paper.category or "",
            difficulty=paper.difficulty or "",
            case_ids=ids,
            question_count=len(ids),
            case_nos=[by_id.get(case_id, "") for case_id in ids],
            entered_count=len(by_user),
            handed_count=handed,
            opened_at=paper.opened_at,
            closed_at=paper.closed_at,
            publisher_name=_person_name(teacher),
            participants=participants,
            audience_scope=(paper.audience_scope or "ALL"),
            audience_values=[str(item) for item in (paper.audience_values or [])],
            audience_ids=[int(item) for item in (paper.audience_ids or [])],
            audience_label=audience_label(db, paper),
            audience_count=len(audience_students(db, paper)) if _is_teacher_or_admin(user) else 0,
            mine_status=mine,
            mine_score=mine_score,
            mine_passed=mine_passed,
            max_attempts=max_attempts,
            current_round=current_round,
            remaining_attempts=remaining_attempts,
            can_retake=can_retake,
            retake_hint=retake_hint,
        )

    @staticmethod
    def start(db: Session, user: User, paper_id: int, retake: bool = False):
        if _is_teacher_or_admin(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="请用学员账号进入考试")
        paper = _paper_or_404(db, paper_id)
        if not paper_reaches(paper, user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="你不在这场考试的受考对象里，请联系老师",
            )
        existing = _sessions(db, paper.id, user.id)
        rounds_map = {}
        for row in existing:
            r = getattr(row, "attempt_round", 1) or 1
            rounds_map.setdefault(r, []).append(row)

        draft = next((row for row in existing if row.status == PracticeStatusEnum.DRAFT.value), None)

        if not retake:
            if draft:
                expire_if_needed(db, draft)
                db.refresh(draft)
                if not paper.allow_back and draft.status == PracticeStatusEnum.DRAFT.value:
                    guard_back(db, draft)
                return _to_out(draft, db)
            if existing:
                latest_rnd = max(rounds_map.keys())
                target = rounds_map[latest_rnd][0]
                return _to_out(target, db)
        else:
            if paper.status != "OPEN":
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="这场考试已经收卷，无法重新考试")
            if draft:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="当前轮次尚在作答中，请先继续作答或交卷",
                )
            completed_rounds = [
                r for r, r_rows in rounds_map.items()
                if all(row.status != PracticeStatusEnum.DRAFT.value for row in r_rows)
            ]
            max_attempts = int(getattr(paper, "max_attempts", 2) or 2)
            if len(completed_rounds) >= max_attempts:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"已达重考上限（每位学员限考 {max_attempts} 次）",
                )

        if paper.status != "OPEN":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="这场考试已经收卷")

        ids = [int(item) for item in (paper.case_ids or [])]
        cases = db.query(TrainingCase).filter(TrainingCase.id.in_(ids)).all() if ids else []
        by_id = {case.id: case for case in cases}
        ordered = [by_id[case_id] for case_id in ids if case_id in by_id]
        if not ordered:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="这场考试没有可用题目")

        next_round = (max(rounds_map.keys()) if rounds_map else 0) + 1
        group_id = f"paper-{paper.id}-{user.id}-r{next_round}"
        first = None
        now = datetime.now()
        for index, case in enumerate(ordered, start=1):
            record = PracticeSession(
                user_id=user.id,
                case_id=case.id,
                mode="SELECTED",
                attempt_kind="EXAM",
                exam_group_id=group_id,
                exam_index=index,
                exam_total=len(ordered),
                exam_paper_id=paper.id,
                attempt_round=next_round,
                status=PracticeStatusEnum.DRAFT.value,
                started_at=now,
            )
            db.add(record)
            db.flush()
            from app.services.practice_service import _ensure_text_paper
            _ensure_text_paper(record, db)
            if first is None:
                first = record
        db.commit()
        db.refresh(first)
        return _to_out(first, db)

    @staticmethod
    def save_draft(db: Session, user: User, paper_id: int, params: PracticeSubmitParams):
        paper = _paper_or_404(db, paper_id)
        record = _own_draft(db, user, paper, params.session_id)
        if not paper.allow_back:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="这场考试要按顺序作答，不能先保存后返回")
        if clock_expired(db, record):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="考试时间已到，请交卷")
        apply_draft(db, record, params)
        db.commit()
        db.refresh(record)
        return _to_out(record, db)

    @staticmethod
    def hand_in(db: Session, user: User, paper_id: int, body):
        paper = _paper_or_404(db, paper_id)
        if paper.status == "CLOSED":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="这场考试已经收卷")
        params = hand_in_as_submit(body)
        record = (
            db.query(PracticeSession)
            .filter(
                PracticeSession.id == params.session_id,
                PracticeSession.exam_paper_id == paper.id,
                PracticeSession.user_id == user.id,
            )
            .first()
        )
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这份答卷")
        if record.status == PracticeStatusEnum.DRAFT.value:
            apply_draft(db, record, params)
            db.commit()
        finalize_user(db, user.id, paper.id)
        notify_exam_handed(db, user, paper)
        db.refresh(record)
        return _to_out(record, db)

    @staticmethod
    def collect(db: Session, user: User, paper_id: int) -> dict:
        _require_teacher(user)
        paper = _paper_or_404(db, paper_id)
        if paper.status == "CLOSED":
            return {"collected": 0, "message": "已经收过卷"}
        user_ids = {row.user_id for row in _sessions(db, paper.id)}
        collected = 0
        for user_id in user_ids:
            collected += finalize_user(db, user_id, paper.id, reason="COLLECT")
        paper.status = "CLOSED"
        paper.closed_at = datetime.now()
        db.commit()
        return {"collected": collected, "entered": len(user_ids), "message": "已收卷"}

    @staticmethod
    def reset_attempt(db: Session, user: User, paper_id: int, student_id: int) -> dict:
        """老师把某个学员的「超时未作答」空白卷清掉，让他重新进入考试。

        只允许重置系统补交的空白卷：学员自己交过、或写过任何内容的卷都不能清，
        避免误删真实成绩。
        """
        _require_teacher(user)
        paper = _paper_or_404(db, paper_id)
        if paper.status != "OPEN":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已收卷的考试不能重置")
        rows = _sessions(db, paper.id, student_id)
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="这名学员还没有进入考试")
        rounds_map = {}
        for row in rows:
            rnd = getattr(row, "attempt_round", 1) or 1
            rounds_map.setdefault(rnd, []).append(row)
        latest_rnd = max(rounds_map.keys())
        latest_rows = rounds_map[latest_rnd]
        if not is_blank_auto_hand_in(latest_rows):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="只能重置超时未作答的空白卷",
            )
        from app.services.op_log_service import OpLogService

        for row in latest_rows:
            db.delete(row)
        OpLogService.record(
            db, user=user, module="training", action="exam_reset",
            detail=(
                f"重置考试「{paper.title}」(#{paper.id}) 学员 #{student_id} 第{latest_rnd}轮超时空白卷，"
                f"清除 {len(latest_rows)} 题记录 {[row.id for row in latest_rows]}"
            ),
            commit=False,
        )
        db.commit()
        return {"removed": len(latest_rows), "message": "已重置，学员可以重新进入考试"}

    @staticmethod
    def remove(db: Session, user: User, paper_id: int) -> None:
        _require_teacher(user)
        paper = _paper_or_404(db, paper_id)
        if _sessions(db, paper.id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已有学员进入，不能删除")
        if paper.status == "CLOSED":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="已收卷的考试要留档")
        db.delete(paper)
        db.commit()

    @staticmethod
    def grade_rows(db: Session, paper: ExamPaper) -> List[dict]:
        sessions = _sessions(db, paper.id)
        by_user: dict = {}
        for row in sessions:
            by_user.setdefault(row.user_id, []).append(row)
        students = audience_students(db, paper)
        seen = {student.id for student in students}
        for user_id, rows in by_user.items():
            if user_id not in seen and rows and rows[0].user is not None:
                students.append(rows[0].user)
        question_count = len(paper.case_ids or [])
        out = []
        line = int(paper.pass_score or 0)
        retake_policy = getattr(paper, "retake_policy", "BEST") or "BEST"
        for student in students:
            mine = by_user.get(student.id, [])
            rounds_map = {}
            for row in mine:
                rnd = getattr(row, "attempt_round", 1) or 1
                rounds_map.setdefault(rnd, []).append(row)

            completed_rounds = [
                rnd for rnd, r_rows in rounds_map.items()
                if all(row.status != PracticeStatusEnum.DRAFT.value for row in r_rows)
            ]

            if not mine:
                state, average, passed, scores = "缺考", None, "缺考", [None] * question_count
            elif completed_rounds:
                best_rnd = None
                best_avg = -1.0
                best_scores = []
                for rnd in sorted(completed_rounds):
                    r_rows = rounds_map[rnd]
                    by_index = {row.exam_index: row for row in r_rows}
                    r_scores = []
                    for index in range(1, question_count + 1):
                        row = by_index.get(index)
                        if row is None or row.status == PracticeStatusEnum.DRAFT.value:
                            r_scores.append(None)
                        else:
                            r_scores.append(round(float(row.score_total or 0), 2))
                    nums = [s for s in r_scores if s is not None]
                    avg = round(sum(nums) / len(nums), 2) if nums else 0.0
                    if retake_policy == "BEST":
                        if avg > best_avg or best_rnd is None:
                            best_avg = avg
                            best_rnd = rnd
                            best_scores = r_scores
                    else:
                        best_avg = avg
                        best_rnd = rnd
                        best_scores = r_scores

                state = "已交卷"
                average = best_avg
                passed = "合格" if average >= line else "不合格"
                scores = best_scores
            else:
                latest_rnd = max(rounds_map.keys())
                latest_rows = rounds_map[latest_rnd]
                if is_blank_auto_hand_in(latest_rows):
                    state, average, passed = "超时未作答", 0.0, "不合格"
                else:
                    state, average, passed = "未交完", None, "未交完"
                by_index = {row.exam_index: row for row in latest_rows}
                scores = []
                for index in range(1, question_count + 1):
                    row = by_index.get(index)
                    if row is None or row.status == PracticeStatusEnum.DRAFT.value:
                        scores.append(None)
                    else:
                        scores.append(round(float(row.score_total or 0), 2))

            out.append({
                "name": student.real_name or student.username,
                "username": student.username,
                "state": state,
                "scores": scores,
                "average": average,
                "pass_score": line,
                "passed": passed,
            })
        return out

    @staticmethod
    def csv_text(db: Session, user: User, paper_id: int) -> str:
        _require_teacher(user)
        paper = _paper_or_404(db, paper_id)
        if paper.status != "CLOSED":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="请先收卷，再导出成绩")
        ids = [int(item) for item in (paper.case_ids or [])]
        cases = db.query(TrainingCase).filter(TrainingCase.id.in_(ids)).all() if ids else []
        case_no = {case.id: case.case_no for case in cases}
        headers = ["姓名", "用户名", "状态"]
        for index, case_id in enumerate(ids, start=1):
            headers.append(f"第{index}题({case_no.get(case_id, case_id)})")
        headers.extend(["平均分", "合格线", "是否合格"])
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(headers)
        for row in ExamService.grade_rows(db, paper):
            scores = ["" if score is None else score for score in row["scores"]]
            average = "" if row["average"] is None else row["average"]
            writer.writerow([
                row["name"], row["username"], row["state"], *scores,
                average, row["pass_score"], row["passed"],
            ])
        return buffer.getvalue()


def _own_draft(db: Session, user: User, paper: ExamPaper, session_id: int) -> PracticeSession:
    record = (
        db.query(PracticeSession)
        .filter(
            PracticeSession.id == session_id,
            PracticeSession.exam_paper_id == paper.id,
            PracticeSession.user_id == user.id,
        )
        .first()
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="没有这份答卷")
    if record.status != PracticeStatusEnum.DRAFT.value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="这题已经交过")
    if paper.status != "OPEN":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="这场考试已经收卷")
    guard_back(db, record)
    return record

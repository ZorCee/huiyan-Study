# -*- coding: utf-8 -*-
"""考试受考对象（可见性、进入、成绩表）与病例关联题的组卷、预览。"""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.models import ExamPaper, Role, RoleEnum, TrainingCase, User
from app.db.models.question import Question
from app.schemas.exam import ExamCreate
from app.services.exam_service import ExamService
from app.services.question_service import QuestionService


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _people(db):
    teacher_role = Role(code=RoleEnum.TEACHER.value, name="教师")
    student_role = Role(code=RoleEnum.STUDENT.value, name="学员")
    db.add_all([teacher_role, student_role])
    db.flush()
    teacher = User(username="teacher", password_hash="x", real_name="李老师",
                   role_id=teacher_role.id, is_active=True)
    a = User(username="a", password_hash="x", real_name="甲", role_id=student_role.id,
             is_active=True, study_year="2025级", rotation_batch="一批", mentor_group="A组")
    b = User(username="b", password_hash="x", real_name="乙", role_id=student_role.id,
             is_active=True, study_year="2025级", rotation_batch="二批", mentor_group="B组")
    c = User(username="c", password_hash="x", real_name="丙", role_id=student_role.id,
             is_active=True, study_year="2024级", rotation_batch="二批", mentor_group="C组")
    db.add_all([teacher, a, b, c])
    db.commit()
    return teacher, a, b, c


def _case(db, teacher, case_no, category="DR"):
    row = TrainingCase(
        case_no=case_no, title=case_no, category=category, difficulty="EASY",
        gold_dr_grade="2", gold_diagnosis="出血", is_published=True,
        is_train_case=True, archive_status="ACTIVE", creator_id=teacher.id,
    )
    db.add(row)
    db.commit()
    return row


def _question(db, stem, case_id=None, tags=None):
    row = Question(question_type="KNOWLEDGE", case_id=case_id, stem=stem,
                   answer="A", tags=tags or [], is_active=True)
    db.add(row)
    db.commit()
    return row


def _paper(db, teacher, case, **audience):
    return ExamService.create(db, teacher, ExamCreate(
        title="月考", pick_mode="SELECTED", case_ids=[case.id], **audience,
    ))


def _visible_ids(db, user):
    return {paper.id for paper in ExamService.list_papers(db, user)}


def test_old_papers_default_to_everyone(db):
    teacher, a, b, c = _people(db)
    case = _case(db, teacher, "T1")
    paper = _paper(db, teacher, case)
    assert paper.audience_scope == "ALL"
    assert paper.audience_label == "全体学员"
    assert paper.audience_count == 3
    for student in (a, b, c):
        assert paper.id in _visible_ids(db, student)


def test_multiple_groups_limit_visibility_and_start(db):
    teacher, a, b, c = _people(db)
    case = _case(db, teacher, "T1")
    paper = _paper(db, teacher, case, audience_scope="GROUP", audience_values=["A组", "B组"])
    assert paper.audience_count == 2
    assert paper.audience_label == "带教组：A组、B组"
    assert paper.id in _visible_ids(db, a)
    assert paper.id in _visible_ids(db, b)
    assert paper.id not in _visible_ids(db, c)
    with pytest.raises(HTTPException) as caught:
        ExamService.start(db, c, paper.id)
    assert caught.value.status_code == 403
    ExamService.start(db, a, paper.id)


def test_people_scope_crosses_groups(db):
    teacher, a, b, c = _people(db)
    case = _case(db, teacher, "T1")
    paper = _paper(db, teacher, case, audience_scope="PEOPLE", audience_ids=[a.id, c.id])
    assert paper.id in _visible_ids(db, a)
    assert paper.id in _visible_ids(db, c)
    assert paper.id not in _visible_ids(db, b)


def test_grade_rows_only_list_targets(db):
    teacher, a, b, c = _people(db)
    case = _case(db, teacher, "T1")
    paper = _paper(db, teacher, case, audience_scope="BATCH", audience_values=["二批"])
    row = db.query(ExamPaper).filter(ExamPaper.id == paper.id).first()
    names = {item["name"] if "name" in item else item.get("姓名") for item in ExamService.grade_rows(db, row)}
    assert "甲" not in names
    assert {"乙", "丙"} <= names


def test_empty_audience_is_refused(db):
    teacher, *_ = _people(db)
    case = _case(db, teacher, "T1")
    with pytest.raises(HTTPException) as caught:
        _paper(db, teacher, case, audience_scope="GROUP", audience_values=["不存在的组"])
    assert caught.value.status_code == 400
    with pytest.raises(HTTPException):
        _paper(db, teacher, case, audience_scope="YEAR", audience_values=[])


def test_generic_fill_prefers_same_category(db):
    teacher, *_ = _people(db)
    case = _case(db, teacher, "T1", category="AMD")
    own = _question(db, "专属", case_id=case.id)
    other = _question(db, "DR 通用", tags=["DR"])
    same = _question(db, "AMD 通用", tags=["AMD"])
    mine, generics = QuestionService.plan_for_case(db, case.id, 4)
    assert [q.id for q in mine] == [own.id]
    assert [q.id for q in generics] == [same.id, other.id]


def test_exam_start_uses_case_questions_and_matches_preview(db):
    teacher, a, *_ = _people(db)
    case = _case(db, teacher, "T1")
    own = [_question(db, f"专属{i}", case_id=case.id) for i in range(2)]
    generic = _question(db, "通用", tags=["DR"])
    paper = _paper(db, teacher, case)

    preview = ExamService.preview(db, teacher, [case.id])
    item = preview.cases[0]
    assert item.own_count == 2
    assert item.generic_count == 1
    assert item.legacy_count == 1
    assert preview.total_questions == 4

    ExamService.start(db, a, paper.id)
    from app.db.models import PracticeSession
    record = db.query(PracticeSession).filter(PracticeSession.exam_paper_id == paper.id).first()
    ids = [str(x) for x in record.text_question_ids]
    assert ids[:3] == [q.id for q in item.questions]
    assert set(ids[:2]) == {str(q.id) for q in own}
    assert ids[2] == str(generic.id)
    assert len(ids) == 4


def test_preview_flags_cases_without_questions(db):
    teacher, *_ = _people(db)
    case = _case(db, teacher, "T1")
    preview = ExamService.preview(db, teacher, [case.id])
    assert preview.cases[0].own_count == 0
    assert preview.cases[0].legacy_count == 4

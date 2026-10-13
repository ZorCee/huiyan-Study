# -*- coding: utf-8 -*-
"""推荐病例下拉：准入条件不变，本人的待处理病例单独返回并说明还差哪一步。"""

import app.db.models  # noqa: F401
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import Role, RoleEnum, TrainingCase, User
from app.services.rotation_service import RotationService


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    try:
        yield session
    finally:
        session.close()


def _users(db):
    roles = {
        code: Role(code=code.value, name=code.value)
        for code in (RoleEnum.TEACHER, RoleEnum.STUDENT)
    }
    db.add_all(roles.values())
    db.flush()
    me = User(username="t1", password_hash="x", real_name="李老师", role_id=roles[RoleEnum.TEACHER].id)
    other = User(username="t2", password_hash="x", real_name="王老师", role_id=roles[RoleEnum.TEACHER].id)
    student = User(username="s1", password_hash="x", real_name="学员", role_id=roles[RoleEnum.STUDENT].id)
    db.add_all([me, other, student])
    db.commit()
    return me, other, student


def _case(db, creator, no, published, train, category="DR", difficulty="MEDIUM", grade="2"):
    case = TrainingCase(
        case_no=no,
        title=f"{no} 标题",
        description="",
        category=category,
        difficulty=difficulty,
        patient_name="x",
        patient_gender="U",
        patient_phone="",
        clinical_info="",
        gold_dr_grade=grade,
        gold_diagnosis="",
        teaching_points="",
        pass_score=60,
        is_published=published,
        is_train_case=train,
        creator_id=creator.id,
    )
    db.add(case)
    db.commit()
    return case


def test_new_upload_is_pending_not_selectable(db):
    me, _, _ = _users(db)
    draft = _case(db, me, "C001", published=False, train=False)
    out = RotationService.options(db, me)
    assert [row.id for row in out.cases] == []
    assert [(row.id, row.missing_step) for row in out.pending_cases] == [(draft.id, "未发布")]


def test_published_but_not_open_says_missing_open(db):
    me, _, _ = _users(db)
    case = _case(db, me, "C002", published=True, train=False)
    out = RotationService.options(db, me)
    assert out.pending_cases[0].id == case.id
    assert out.pending_cases[0].missing_step == "未开放练习"


def test_open_case_becomes_selectable_with_filter_fields(db):
    me, _, _ = _users(db)
    case = _case(db, me, "C003", published=True, train=True, category="AMD", difficulty="HARD", grade="0")
    out = RotationService.options(db, me)
    assert out.pending_cases == []
    item = out.cases[0]
    assert (item.id, item.category, item.difficulty, item.gold_dr_grade) == (case.id, "AMD", "HARD", "0")
    dumped = out.model_dump(by_alias=True)
    assert "pendingCases" in dumped and "goldDrGrade" in dumped["cases"][0]


def test_other_teachers_drafts_hidden(db):
    me, other, _ = _users(db)
    _case(db, other, "C010", published=False, train=False)
    shared = _case(db, other, "C011", published=True, train=True)
    out = RotationService.options(db, me)
    assert [row.id for row in out.cases] == [shared.id]
    assert out.pending_cases == []


def test_student_forbidden(db):
    _, _, student = _users(db)
    with pytest.raises(HTTPException) as err:
        RotationService.options(db, student)
    assert err.value.status_code == 403

# -*- coding: utf-8 -*-
"""「开放给全体学员练习」不再顺带发布：草稿金标准不能被学员看到。"""

import app.db.models  # noqa: F401
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import Role, RoleEnum, TrainingCase, User
from app.services.case_browse_service import CaseBrowseService


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng)()
    try:
        yield session
    finally:
        session.close()


def _admin(db):
    role = Role(code=RoleEnum.ADMIN.value, name="管理员")
    db.add(role)
    db.flush()
    admin = User(username="admin", password_hash="x", real_name="管理员", role_id=role.id)
    db.add(admin)
    db.commit()
    return admin


def _case(db, admin, *, published):
    case = TrainingCase(
        case_no="IDRID-T-IDRiD_78",
        title="IDRiD_78 · 中度 NPDR",
        description="",
        category="DR",
        difficulty="MEDIUM",
        patient_name="x",
        patient_gender="U",
        patient_phone="",
        clinical_info="",
        gold_dr_grade="2",
        gold_diagnosis="中度",
        teaching_points="",
        pass_score=60,
        is_published=published,
        is_train_case=False,
        creator_id=admin.id,
    )
    db.add(case)
    db.commit()
    return case


def test_unpublished_case_is_rejected_and_stays_draft(db):
    admin = _admin(db)
    case = _case(db, admin, published=False)
    with pytest.raises(HTTPException) as exc:
        CaseBrowseService.join_training(db, admin, case.id)
    assert exc.value.status_code == 400
    assert "尚未发布" in exc.value.detail
    db.refresh(case)
    assert case.is_published is False
    assert case.is_train_case is False


def test_published_case_opens_without_touching_publish_flag(db):
    admin = _admin(db)
    case = _case(db, admin, published=True)
    CaseBrowseService.join_training(db, admin, case.id)
    db.refresh(case)
    assert case.is_train_case is True
    assert case.is_published is True


def test_join_is_idempotent_for_already_open_case(db):
    admin = _admin(db)
    case = _case(db, admin, published=True)
    CaseBrowseService.join_training(db, admin, case.id)
    CaseBrowseService.join_training(db, admin, case.id)
    db.refresh(case)
    assert case.is_train_case is True

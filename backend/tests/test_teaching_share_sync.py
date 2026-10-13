# -*- coding: utf-8 -*-
"""老师端上架、改范围、续期、下架后，学生端「教师演示病例」立即同步。"""

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import Role, RoleEnum, TeachingShare, TrainingCase, User
from app.schemas.teaching import (
    TeachingReviewParams,
    TeachingShareCreate,
    TeachingShareUpdate,
    TeachingSubmitCreate,
)
from app.services.teaching_service import TeachingService


def _db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    return sessionmaker(bind=eng)()


def _setup(db):
    roles = {
        code: Role(code=code.value, name=name)
        for code, name in [
            (RoleEnum.TEACHER, "教师"), (RoleEnum.STUDENT, "学员"), (RoleEnum.ADMIN, "管理员"),
        ]
    }
    db.add_all(roles.values())
    db.flush()
    teacher = User(username="t", password_hash="x", real_name="李老师", role_id=roles[RoleEnum.TEACHER].id)
    other = User(username="t2", password_hash="x", real_name="王老师", role_id=roles[RoleEnum.TEACHER].id)
    admin = User(username="adm", password_hash="x", real_name="管理员", role_id=roles[RoleEnum.ADMIN].id)
    a = User(username="a", password_hash="x", real_name="甲", role_id=roles[RoleEnum.STUDENT].id, study_year="2024级")
    b = User(username="b", password_hash="x", real_name="乙", role_id=roles[RoleEnum.STUDENT].id, study_year="2025级")
    db.add_all([teacher, other, admin, a, b])
    db.flush()
    case = TrainingCase(case_no="T1", title="课堂病例", creator_id=teacher.id)
    db.add(case)
    db.commit()
    return teacher, other, admin, a, b, case


def _seen(db, user):
    return {item.id for item in TeachingService.list_for_student(db, user=user).list}


def _temp(db, teacher, case, **kw):
    return TeachingService.create_temp_share(
        db, user=teacher,
        params=TeachingShareCreate(source_type="TRAINING", source_case_id=case.id, **kw),
    )


def test_long_term_share_never_expires_until_revoked():
    db = _db()
    teacher, _, _, a, _, case = _setup(db)
    shared = _temp(db, teacher, case, expire_hours=0)
    assert shared.expired_at is None
    assert shared.id in _seen(db, a)
    assert TeachingService.get_student_case_detail(db, share_id=shared.id, user=a).id == shared.id

    TeachingService.revoke_share(db, user=teacher, share_id=shared.id)
    assert shared.id not in _seen(db, a)
    db.close()


def test_update_scope_moves_share_between_groups():
    db = _db()
    teacher, _, _, a, b, case = _setup(db)
    shared = _temp(db, teacher, case, share_scope="YEAR", scope_value="2024级")
    assert shared.id in _seen(db, a) and shared.id not in _seen(db, b)

    TeachingService.update_share(
        db, user=teacher, share_id=shared.id,
        params=TeachingShareUpdate(share_scope="YEAR", scope_value="2025级", expire_hours=24),
    )
    assert shared.id not in _seen(db, a)
    assert shared.id in _seen(db, b)
    with pytest.raises(HTTPException) as err:
        TeachingService.get_student_case_detail(db, share_id=shared.id, user=a)
    assert err.value.status_code == 403
    db.close()


def test_renew_brings_expired_share_back():
    db = _db()
    teacher, _, _, a, _, case = _setup(db)
    shared = _temp(db, teacher, case)
    row = db.query(TeachingShare).get(shared.id)
    row.expired_at = datetime.now() - timedelta(hours=1)
    db.commit()
    assert shared.id not in _seen(db, a)

    renewed = TeachingService.update_share(
        db, user=teacher, share_id=shared.id,
        params=TeachingShareUpdate(share_scope="ALL", expire_hours=48),
    )
    assert renewed.expired_at > datetime.now() + timedelta(hours=47)
    assert shared.id in _seen(db, a)
    db.close()


def test_update_rejects_other_teacher_and_revoked_share():
    db = _db()
    teacher, other, _, _, _, case = _setup(db)
    shared = _temp(db, teacher, case)
    params = TeachingShareUpdate(share_scope="ALL", expire_hours=24)
    with pytest.raises(HTTPException) as err:
        TeachingService.update_share(db, user=other, share_id=shared.id, params=params)
    assert err.value.status_code == 403

    TeachingService.revoke_share(db, user=teacher, share_id=shared.id)
    with pytest.raises(HTTPException) as err:
        TeachingService.update_share(db, user=teacher, share_id=shared.id, params=params)
    assert err.value.status_code == 400
    db.close()


def test_teacher_shelves_own_approved_case():
    db = _db()
    teacher, other, admin, a, _, case = _setup(db)
    submitted = TeachingService.submit_for_review(
        db, user=teacher,
        params=TeachingSubmitCreate(source_type="TRAINING", source_case_id=case.id, title="入库病例"),
    )
    assert submitted.id not in _seen(db, a)
    TeachingService.review(
        db, reviewer=admin, share_id=submitted.id, params=TeachingReviewParams(accept=True),
    )
    assert submitted.id in _seen(db, a)

    with pytest.raises(HTTPException) as err:
        TeachingService.shelve(db, user=other, share_id=submitted.id, owner_only=True)
    assert err.value.status_code == 403

    shelved = TeachingService.shelve(db, user=teacher, share_id=submitted.id, owner_only=True)
    assert shelved.status == "SHELVED"
    assert submitted.id not in _seen(db, a)
    with pytest.raises(HTTPException):
        TeachingService.get_student_case_detail(db, share_id=submitted.id, user=a)
    db.close()


def test_rejected_case_stays_hidden():
    db = _db()
    teacher, _, admin, a, _, case = _setup(db)
    submitted = TeachingService.submit_for_review(
        db, user=teacher,
        params=TeachingSubmitCreate(source_type="TRAINING", source_case_id=case.id),
    )
    TeachingService.review(
        db, reviewer=admin, share_id=submitted.id,
        params=TeachingReviewParams(accept=False, comment="图像不清晰"),
    )
    assert submitted.id not in _seen(db, a)
    db.close()

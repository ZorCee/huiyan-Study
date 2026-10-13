# -*- coding: utf-8 -*-
"""回归测试公用数据。只用内存 SQLite，人员与病例全部为脱敏假数据，不连任何真实库。

每个用例函数的 docstring 按固定格式书写，报告生成器会读取：
    编号 | 名称
    前置: ...
    步骤: ...
    预期: ...
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db.models  # noqa: F401
from app.db.base import Base
from app.db.models import PracticeSession, Role, RoleEnum, TrainingCase, User
from app.schemas.exam import ExamCreate
from app.services.exam_service import ExamService


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def people(db):
    """学员 2 名、老师 1 名、管理员 1 名，姓名均为假名。"""
    roles = {}
    for code, name in (
        (RoleEnum.STUDENT, "学员"),
        (RoleEnum.TEACHER, "教师"),
        (RoleEnum.ADMIN, "管理员"),
    ):
        roles[code] = Role(code=code.value, name=name)
    db.add_all(roles.values())
    db.flush()

    def make(username, real_name, role):
        return User(
            username=username, password_hash="x", real_name=real_name,
            role_id=roles[role].id, is_active=True,
        )

    rows = {
        "student": make("reg_stu_a", "测试学员甲", RoleEnum.STUDENT),
        "student_b": make("reg_stu_b", "测试学员乙", RoleEnum.STUDENT),
        "teacher": make("reg_tea", "测试教师", RoleEnum.TEACHER),
        "admin": make("reg_adm", "测试管理员", RoleEnum.ADMIN),
    }
    db.add_all(rows.values())
    db.commit()
    return rows


def make_case(db, creator, case_no):
    row = TrainingCase(
        case_no=case_no, title=case_no, category="DR", difficulty="EASY",
        gold_dr_grade="2", gold_diagnosis="出血",
        is_published=True, is_train_case=True, archive_status="ACTIVE",
        creator_id=creator.id,
    )
    db.add(row)
    db.commit()
    return row


def make_paper(db, teacher, title="回归考试", count=1):
    cases = [make_case(db, teacher, f"REG-{title}-{i}") for i in range(count)]
    return ExamService.create(db, teacher, ExamCreate(
        title=title, duration_minutes=20, allow_back=True,
        pick_mode="SELECTED", case_ids=[c.id for c in cases],
    ))


def mine_status(db, user, paper_id):
    return next(p for p in ExamService.list_papers(db, user) if p.id == paper_id).mine_status


def expire(db, session_id):
    row = db.query(PracticeSession).filter(PracticeSession.id == session_id).one()
    row.started_at = datetime.now() - timedelta(hours=2)
    db.commit()

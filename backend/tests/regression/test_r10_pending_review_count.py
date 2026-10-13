# -*- coding: utf-8 -*-
"""R10 作业批阅角标与列表口径一致。"""

from app.db.models import ReadingAnnotation
from app.schemas.reading import ReadingListQuery, ReadingReviewParams
from app.services.reading_service import ReadingService

from .conftest import make_case


def _badge(db, user):
    """与前端 usePendingReviewCount 同口径：status=SUBMITTED, page=1, pageSize=1。"""
    return ReadingService.list_records(
        db, user, ReadingListQuery(status="SUBMITTED", page=1, page_size=1)
    ).total


def _list(db, user):
    """与「作业批阅」列表同口径：status=SUBMITTED，不带 caseId。"""
    page = ReadingService.list_records(
        db, user, ReadingListQuery(status="SUBMITTED", page=1, page_size=20)
    )
    return page.total, len(page.list)


def _submit(db, student, case, kind="READING"):
    row = ReadingAnnotation(
        case_id=case.id, user_id=student.id, image_index=0, image_url="",
        status="SUBMITTED", record_kind=kind,
    )
    db.add(row)
    db.commit()
    return row


def test_r10_01_badge_matches_list_through_review(db, people):
    """R10-01 | 提交 → 批阅后角标与列表同步归零
    前置: 老师账号，无待批阅
    步骤: 学员提交 1 份作业；老师批阅通过
    预期: 每一步角标数 = 列表总数 = 列表行数；批阅后均为 0
    """
    teacher, student = people["teacher"], people["student"]
    case = make_case(db, teacher, "REG-R10-01")

    assert _badge(db, teacher) == 0
    assert _list(db, teacher) == (0, 0)

    record = _submit(db, student, case)
    assert _badge(db, teacher) == 1
    assert _list(db, teacher) == (1, 1)

    ReadingService.review(db, teacher, record.id, ReadingReviewParams(accept=True))
    assert _badge(db, teacher) == 0
    assert _list(db, teacher) == (0, 0)


def test_r10_02_reject_also_clears(db, people):
    """R10-02 | 驳回同样清掉待批阅
    前置: 两名学员各提交 1 份（含 1 份图像质控）
    步骤: 老师驳回其中 1 份
    预期: 角标从 2 变为 1，与列表一致
    """
    teacher = people["teacher"]
    case = make_case(db, teacher, "REG-R10-02")
    a = _submit(db, people["student"], case)
    _submit(db, people["student_b"], case, kind="QUALITY")

    assert _badge(db, teacher) == 2
    ReadingService.review(
        db, teacher, a.id, ReadingReviewParams(accept=False, review_comment="请补充")
    )
    assert _badge(db, teacher) == 1
    assert _list(db, teacher) == (1, 1)


def test_r10_03_admin_same_scope_as_teacher(db, people):
    """R10-03 | 管理员与老师统计范围一致
    前置: 学员提交 1 份
    预期: 老师、管理员的角标都是 1
    """
    case = make_case(db, people["teacher"], "REG-R10-03")
    _submit(db, people["student"], case)
    assert _badge(db, people["teacher"]) == 1
    assert _badge(db, people["admin"]) == 1

# -*- coding: utf-8 -*-
"""第 9 项 考试结果页金标准可见性。⚠️ 涉及考试规则：已交卷未收卷时不可见（按确认后的口径）。

每个阶段同时检查：get_detail 返回的 gold_visible / gold_lock_reason，
以及 get_gold_standard 接口是否放行、拒绝时报错文字是否和页面提示一致。
"""

import pytest
from fastapi import HTTPException

from app.db.models.practice_session import PracticeSession
from app.schemas.practice import PracticeStartParams, PracticeSubmitParams
from app.services import practice_service as ps
from app.services.exam_service import ExamService
from app.services.practice_service import PracticeService

from .conftest import make_case, make_paper


def _submit(db, user, session_id, rid):
    return PracticeService.submit(db, user, PracticeSubmitParams(
        session_id=session_id, student_dr_grade="2", student_diagnosis="出血", request_id=rid,
    ))


def _assert_locked(db, user, record, reason):
    detail = PracticeService.get_detail(db, user, record.id)
    assert detail.gold_visible is False
    assert detail.gold_lock_reason == reason
    with pytest.raises(HTTPException) as denied:
        PracticeService.get_gold_standard(db, user, record.case_id, record.id)
    assert denied.value.status_code == 403
    assert denied.value.detail == reason, "接口报错和页面提示应为同一句话"


def _assert_open(db, user, record):
    detail = PracticeService.get_detail(db, user, record.id)
    assert detail.gold_visible is True
    assert detail.gold_lock_reason == ""
    assert PracticeService.get_gold_standard(db, user, record.case_id, record.id) is not None


def test_r9_01_practice_locked_then_open(db, people):
    """R9-01 | 平时练习：提交前锁定，提交后可见
    前置: 学员甲开始一道平时练习
    步骤: 提交前查看金标准 → 提交 → 再次查看
    预期: 提交前不可见，提示"提交本题后即可查看金标准。"，接口 403 且同文案；提交后可见
    """
    case = make_case(db, people["teacher"], "REG-P-1")
    rec = PracticeService.start(db, people["student"], PracticeStartParams(case_id=case.id))
    _assert_locked(db, people["student"], rec, ps.GOLD_REASON_PRACTICE_DRAFT)
    _submit(db, people["student"], rec.id, "r9-01")
    _assert_open(db, people["student"], rec)


def test_r9_02_exam_in_progress_is_blocked(db, people):
    """R9-02 | 考试中：拦截并提示
    前置: 学员甲进入正式考试，尚未提交
    步骤: 查看金标准
    预期: 不可见，提示"交卷后，等老师收卷才能查看金标准。"，接口 403 且同文案
    """
    paper = make_paper(db, people["teacher"])
    rec = ExamService.start(db, people["student"], paper.id)
    _assert_locked(db, people["student"], rec, ps.GOLD_REASON_EXAM_DRAFT)


def test_r9_03_handed_waits_for_collect(db, people):
    """R9-03 | 已交卷未收卷：提示等待收卷
    前置: 学员甲已交卷，老师未收卷
    步骤: 查看金标准
    预期: 不可见，提示"你已交卷。老师收卷后公布答案和金标准。"，接口 403 且同文案
    """
    paper = make_paper(db, people["teacher"])
    rec = ExamService.start(db, people["student"], paper.id)
    _submit(db, people["student"], rec.id, "r9-03")
    _assert_locked(db, people["student"], rec, ps.GOLD_REASON_EXAM_WAIT_CLOSE)


def test_r9_04_collected_is_open(db, people):
    """R9-04 | 已收卷 / 已出分：允许查看
    前置: 学员甲已交卷，老师已收卷
    步骤: 查看详情与金标准
    预期: 可见；answers_open 为真；不再出现"需交卷"类提示
    """
    paper = make_paper(db, people["teacher"])
    rec = ExamService.start(db, people["student"], paper.id)
    _submit(db, people["student"], rec.id, "r9-04")
    ExamService.collect(db, people["teacher"], paper.id)
    assert PracticeService.get_detail(db, people["student"], rec.id).answers_open is True
    _assert_open(db, people["student"], rec)


@pytest.mark.parametrize("role", ["teacher", "admin"])
def test_r9_05_teacher_admin_after_item_submitted(db, people, role):
    """R9-05 | 老师 / 管理员：学员交了这道题后可见
    前置: 学员甲进入考试
    步骤: 老师（或管理员）在学员提交前、提交后分别查看
    预期: 提交前不可见，提示"学员还没有交这道题，交卷后可查看金标准。"；提交后无需收卷即可见
    """
    paper = make_paper(db, people["teacher"])
    rec = ExamService.start(db, people["student"], paper.id)
    viewer = people[role]
    allowed, reason = ps.gold_access(db, rec, viewer)
    assert (allowed, reason) == (False, ps.GOLD_REASON_TEACHER_DRAFT)
    _submit(db, people["student"], rec.id, "r9-05")
    session_row = db.query(PracticeSession).filter(PracticeSession.id == rec.id).one()
    assert ps.gold_access(db, session_row, viewer) == (True, "")
    assert PracticeService.get_gold_standard(db, viewer, rec.case_id, rec.id) is not None


def test_r9_06_other_student_cannot_peek(db, people):
    """R9-06 | 其他学员不能借 session_id 查看
    前置: 学员甲已交卷且老师已收卷
    步骤: 学员乙带着甲的 session_id 请求金标准
    预期: 被拒绝（HTTP 4xx）
    """
    paper = make_paper(db, people["teacher"])
    rec = ExamService.start(db, people["student"], paper.id)
    _submit(db, people["student"], rec.id, "r9-06")
    ExamService.collect(db, people["teacher"], paper.id)
    with pytest.raises(HTTPException) as denied:
        PracticeService.get_gold_standard(db, people["student_b"], rec.case_id, rec.id)
    assert 400 <= denied.value.status_code < 500

# -*- coding: utf-8 -*-
"""第 6 项 考试版本进入。⚠️ 涉及考试规则：重考按"超时白卷由老师重置"口径。"""

import pytest
from fastapi import HTTPException

from app.schemas.practice import PracticeStartParams, PracticeSubmitParams
from app.services.exam_service import ExamService
from app.services.practice_service import PracticeService

from .conftest import expire, make_case, make_paper, mine_status


def _submit(db, user, session_id, rid):
    return PracticeService.submit(db, user, PracticeSubmitParams(
        session_id=session_id, student_dr_grade="2", student_diagnosis="出血", request_id=rid,
    ))


def test_r6_01_fresh_student_can_enter(db, people):
    """R6-01 | 未考学员可以进入考试
    前置: 老师发布 1 道题的考试，学员甲从未进入
    步骤: 查看考试列表状态 → 调用 start 进入
    预期: 进入前状态 READY；进入后状态 DOING，记录未提交
    """
    paper = make_paper(db, people["teacher"])
    assert mine_status(db, people["student"], paper.id) == "READY"
    started = ExamService.start(db, people["student"], paper.id)
    assert started.status != "SUBMITTED"
    assert mine_status(db, people["student"], paper.id) == "DOING"


def test_r6_02_timeout_blank_reset_allows_retake(db, people):
    """R6-02 | 超时白卷经老师重置后可以重考
    前置: 学员甲进入考试后不作答，超过时限被自动收卷
    步骤: 学员自己调用重置 → 老师调用重置 → 学员再次进入
    预期: 白卷状态为 TIMEOUT_BLANK（不是已交卷）；学员自己重置返回 403；老师重置后状态回到 READY，可再次进入
    """
    paper = make_paper(db, people["teacher"])
    started = ExamService.start(db, people["student"], paper.id)
    expire(db, started.id)
    PracticeService.get_detail(db, people["student"], started.id)
    assert mine_status(db, people["student"], paper.id) == "TIMEOUT_BLANK"
    with pytest.raises(HTTPException) as denied:
        ExamService.reset_attempt(db, people["student"], paper.id, people["student"].id)
    assert denied.value.status_code == 403
    ExamService.reset_attempt(db, people["teacher"], paper.id, people["student"].id)
    assert mine_status(db, people["student"], paper.id) == "READY"
    ExamService.start(db, people["student"], paper.id)
    assert mine_status(db, people["student"], paper.id) == "DOING"


def test_r6_03_handed_in_cannot_be_reset(db, people):
    """R6-03 | 正常交卷的记录不允许重置
    前置: 学员甲进入考试并提交答案
    步骤: 老师调用重置
    预期: 状态为 HANDED；重置被拒绝（HTTP 4xx），成绩不被清掉
    """
    paper = make_paper(db, people["teacher"])
    started = ExamService.start(db, people["student"], paper.id)
    _submit(db, people["student"], started.id, "r6-03")
    assert mine_status(db, people["student"], paper.id) == "HANDED"
    with pytest.raises(HTTPException) as denied:
        ExamService.reset_attempt(db, people["teacher"], paper.id, people["student"].id)
    assert 400 <= denied.value.status_code < 500
    assert mine_status(db, people["student"], paper.id) == "HANDED"


def test_r6_04_practice_submit_does_not_touch_exam(db, people):
    """R6-04 | 平时练习（标注版本）提交不影响考试状态
    前置: 一场未进入的考试；另有一道平时练习病例
    步骤: 学员甲完成并提交平时练习 → 查看考试状态
    预期: 考试状态仍为 READY，不会变成已考完
    """
    paper = make_paper(db, people["teacher"])
    case = make_case(db, people["teacher"], "REG-PRACTICE-1")
    own = PracticeService.start(db, people["student"], PracticeStartParams(case_id=case.id))
    _submit(db, people["student"], own.id, "r6-04")
    assert mine_status(db, people["student"], paper.id) == "READY"


def test_r6_05_other_student_status_is_independent(db, people):
    """R6-05 | 不会出现"未考却显示已考完"
    前置: 学员甲已交卷，学员乙从未进入
    步骤: 分别查看两人的考试状态
    预期: 甲为 HANDED，乙为 READY
    """
    paper = make_paper(db, people["teacher"])
    started = ExamService.start(db, people["student"], paper.id)
    _submit(db, people["student"], started.id, "r6-05")
    assert mine_status(db, people["student"], paper.id) == "HANDED"
    assert mine_status(db, people["student_b"], paper.id) == "READY"


def test_r6_06_self_test_does_not_reuse_formal_draft(db, people):
    """R6-06 | 自测考试不会接续正式考试的未交记录
    前置: 学员甲正式考试进行中
    步骤: 学员甲发起自测考试
    预期: 自测生成新的记录，id 与正式考试记录不同
    """
    paper = make_paper(db, people["teacher"])
    formal = ExamService.start(db, people["student"], paper.id)
    make_case(db, people["teacher"], "REG-SELF-1")
    own = PracticeService.start_exam(db, people["student"])
    assert own.id != formal.id

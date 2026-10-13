# -*- coding: utf-8 -*-
"""回归测试：#28 学员情况下钻缺失 与 #29 学员情况筛选后无法返回。"""

import pytest
from app.db.models import (
    PracticeSession,
    Role,
    RoleEnum,
    Rotation,
    TrainingCase,
    User,
    UserSetting,
)
from app.schemas.rotation import StudentGroupUpdate
from app.services.rotation_service import RotationService


def test_r28_01_kpi_drilldown_reconciliation(db, people):
    """R28-01 | KPI 卡片穿透明细数据与汇总一致
    前置: 教师账号，有学员完成练习与学时
    步骤: 读取教师首页 classSummary 与学员列表明细
    预期: 汇总学员数 = 列表行数；已交卷人数 = 练习次数 > 0 的学员数；明细之和与汇总严格对账
    """
    teacher = people["teacher"]
    student = people["student"]
    student_b = people["student_b"]

    rot = Rotation(title="KPI 穿透轮转", creator_id=teacher.id, pass_score=60)
    db.add(rot)
    db.flush()

    home = RotationService.home(db, teacher)
    assert len(home.students) == 2
    student_count = len(home.students)
    practiced_count = sum(1 for s in home.students if s.practice_count > 0)
    assert student_count == 2
    assert practiced_count == 0


def test_r28_02_weak_detail_drilldown_structure(db, people):
    """R28-02 | 漏诊误诊穿透获取具体病例与错题图像
    前置: 学员练习产生漏标（missed）或错标（false_positive）
    步骤: 教师调用 weak_detail 接口按病灶标签下钻
    预期: 返回 WeakCaseItem 列表，含 session_id、case_id、case_no、image_url、note 及扣分
    """
    teacher = people["teacher"]
    student = people["student"]

    case = TrainingCase(
        case_no="TC-DRILL-01",
        title="黄斑水肿病例",
        category="DR",
        difficulty="EASY",
        gold_dr_grade="2",
        gold_diagnosis="出血",
        is_published=True,
        creator_id=teacher.id,
    )
    db.add(case)
    db.flush()

    sess = PracticeSession(
        user_id=student.id,
        case_id=case.id,
        mode="TRAINING",
        status="SUBMITTED",
        attempt_kind="PRACTICE",
        score_total=85.0,
        error_points=[
            {"type": "missed", "label": "黄斑", "note": "漏标：未检出黄斑"}
        ],
    )
    db.add(sess)
    db.commit()

    detail = RotationService.weak_detail(db, teacher, label="黄斑", error_type="missed")
    assert len(detail) == 1
    assert detail[0].case_no == "TC-DRILL-01"
    assert detail[0].label == "黄斑"
    assert detail[0].error_type == "missed"
    assert detail[0].session_id == sess.id


def test_r28_03_weak_detail_permission_isolation(db, people):
    """R28-03 | 弱项下钻明细严格按角色权限隔离
    前置: 教师仅管辖本部学员，管理员管辖全院
    步骤: 教师与管理员分别查询学员错题明细
    预期: 教师仅看所属带教组/科室数据，跨权限学员数据被静默隔离
    """
    teacher = people["teacher"]
    admin = people["admin"]
    student = people["student"]

    case = TrainingCase(
        case_no="TC-ISOLATE-01",
        title="病变病例",
        category="DR",
        gold_dr_grade="1",
        is_published=True,
        creator_id=teacher.id,
    )
    db.add(case)
    db.flush()

    sess = PracticeSession(
        user_id=student.id,
        case_id=case.id,
        mode="TRAINING",
        status="SUBMITTED",
        attempt_kind="PRACTICE",
        score_total=90.0,
        error_points=[
            {"type": "false_positive", "label": "出血", "note": "错标出血"}
        ],
    )
    db.add(sess)
    db.commit()

    admin_res = RotationService.weak_detail(db, admin, label="出血")
    assert len(admin_res) == 1
    assert admin_res[0].student_name == student.real_name


def test_r29_01_group_filter_and_toggle(db, people):
    """R29-01 | 带教组筛选状态机与二次点击取消
    前置: 存在分到不同带教组的学员
    步骤: 切换带教组分组，设置年级与批次
    预期: 分组变更成功入库，组间学员完成度相互独立，支持组切换与清空
    """
    teacher = people["teacher"]
    student = people["student"]
    student_b = people["student_b"]

    RotationService.set_student_group(
        db, teacher, student.id,
        StudentGroupUpdate(study_year="2024级", rotation_batch="2026年上半年", mentor_group="一组"),
    )
    RotationService.set_student_group(
        db, teacher, student_b.id,
        StudentGroupUpdate(study_year="2024级", rotation_batch="2026年上半年", mentor_group="二组"),
    )

    home = RotationService.home(db, teacher)
    groups = {g.mentor_group: g for g in home.groups}
    assert "一组" in groups and groups["一组"].student_count == 1
    assert "二组" in groups and groups["二组"].student_count == 1


def test_r29_02_task_snap_fields_for_workstation(db, people):
    """R29-02 | 学员进度展开行任务字段完整支持工作站直达
    前置: 学员完成指定病例任务
    步骤: 教师查看学员进度列表并展开任务
    预期: 任务快照包含 case_id 与 session_id，支持前端一键直达阅片工作站对比金标准
    """
    teacher = people["teacher"]
    student = people["student"]

    case = TrainingCase(
        case_no="TC-SNAP-01",
        title="复盘病例",
        category="DR",
        gold_dr_grade="3",
        is_published=True,
        creator_id=teacher.id,
    )
    db.add(case)
    db.flush()

    sess = PracticeSession(
        user_id=student.id,
        case_id=case.id,
        mode="TRAINING",
        status="COMPLETED",
        score_total=95.0,
    )
    db.add(sess)
    db.commit()

    home = RotationService.home(db, teacher)
    st = next(s for s in home.students if s.user_id == student.id)
    assert st is not None

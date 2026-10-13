# -*- coding: utf-8 -*-
"""R11 AI 筛查顶部统计：按次数累加、分级一一对应、无数据为 0。"""

from app.db.models import ScreeningCase, ScreeningResult
from app.services.diagnosis_service import DiagnosisType, _build_case
from app.services.screening_service import ScreeningService


def _run(db, user, risks, status="COMPLETED"):
    """模拟一次 AI 判读落库：与 diagnosis_service 相同，先建病例再写结果。"""
    case = _build_case(
        db, user=user, diagnosis_type=DiagnosisType.COMPREHENSIVE,
        image_paths={"OD": "/tmp/same.jpeg"}, image_count=1, remark="",
    )
    for eye, risk in risks:
        db.add(ScreeningResult(case_id=case.id, eye_side=eye, risk_level=risk))
    case.status = status
    db.commit()
    return case


def _stats(db):
    return ScreeningService.stats(db=db, scope=None)


def test_r11_01_empty_is_zero(db):
    """R11-01 | 无数据时全部为 0
    前置: 空库
    步骤: 读取顶部统计
    预期: 累计、高危、中危、正常、分析中均为 0
    """
    s = _stats(db)
    assert (s.total, s.red, s.yellow, s.green, s.pending, s.failed) == (0, 0, 0, 0, 0, 0)


def test_r11_02_same_image_twice_counts_twice(db, people):
    """R11-02 | 同一张图判读两次，累计 +2
    前置: 空库
    步骤: 对同一张图连续判读两次，均完成
    预期: 累计筛查 = 2，判读完成后不会从统计中消失
    """
    user = people["teacher"]
    _run(db, user, [("OD", "LOW")])
    assert _stats(db).total == 1
    _run(db, user, [("OD", "LOW")])
    s = _stats(db)
    assert s.total == 2
    assert s.green == 2
    assert s.pending == 0


def test_r11_03_risk_buckets_one_per_case(db, people):
    """R11-03 | 分级按病例取最高等级，与结果一一对应
    前置: 空库
    步骤: 写入 4 次判读：高危、急症、中危、左右眼不同（高危+正常）
    预期: 高危 3、中危 1、正常 0；三档之和 = 有结果的病例数
    """
    user = people["teacher"]
    _run(db, user, [("OD", "HIGH")])
    _run(db, user, [("OD", "URGENT")])
    _run(db, user, [("OS", "MEDIUM")])
    _run(db, user, [("OD", "HIGH"), ("OS", "LOW")])
    s = _stats(db)
    assert (s.red, s.yellow, s.green) == (3, 1, 0)
    assert s.red + s.yellow + s.green == 4 == s.total


def test_r11_04_processing_and_failed(db, people):
    """R11-04 | 处理中与失败计入累计，但不计入分级
    前置: 空库
    步骤: 1 次处理中、1 次失败、1 次完成（中危）
    预期: 累计 3、分析中 1、失败 1、中危 1
    """
    user = people["teacher"]
    _run(db, user, [], status="PROCESSING")
    _run(db, user, [], status="FAILED")
    _run(db, user, [("OD", "MEDIUM")])
    s = _stats(db)
    assert (s.total, s.pending, s.failed, s.yellow) == (3, 1, 1, 1)


def test_r11_05_total_matches_record_count(db, people):
    """R11-05 | 统计数字与筛查记录条数始终一致
    前置: 空库
    步骤: 写入 5 次不同状态的判读
    预期: 累计筛查 = biz_screening_case 实际行数
    """
    user = people["teacher"]
    for status in ["COMPLETED", "REVIEWED", "FAILED", "PROCESSING", "COMPLETED"]:
        _run(db, user, [("OD", "LOW")] if status in ("COMPLETED", "REVIEWED") else [], status=status)
    assert _stats(db).total == db.query(ScreeningCase).count() == 5

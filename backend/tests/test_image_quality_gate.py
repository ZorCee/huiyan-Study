# -*- coding: utf-8 -*-
"""
图像质量门控测试

对应《医学培训端评估与工作流重构报告》：
    P0「低质量 / 遮挡 / 空白图 → 标记不可判读；AI 不返回正常；允许重拍 / 转诊」
    风险表「算法服务单点：质量门控失败时降级为『未评估』而非阻断」
"""

import pytest

from app.common.image_safety import build_image_meta, summarize_safety
from app.services.image_quality_service import normalize_quality, parse_upstream


class FakeQuality:
    def __init__(self, quality, confidence=0.9):
        self.quality = quality
        self.confidence = confidence


class FakeImage:
    def __init__(self, img_id, url="/static/a.jpg", eye="OD", role="original"):
        self.id = img_id
        self.file_url = url
        self.eye = eye
        self.role = role
        self.file_name = ""


# --------------------------------------------------------------------------
# 上游结果解析
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("good", "good"), ("usable", "usable"), ("poor", "poor"),
    ("Good", "good"), ("POOR", "poor"),
    ("好", "good"), ("可用", "usable"), ("差", "poor"),
])
def test_normalize_quality(raw, expected):
    assert normalize_quality(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "未知类别", "xyz"])
def test_normalize_quality_unknown_not_guessed(raw):
    """无法识别的类别必须退化为 unknown，绝不猜成 good"""
    assert normalize_quality(raw) == "unknown"


def test_parse_upstream_full():
    payload = {
        "model": {"name": "Image_quality", "task_type": "image_quality"},
        "result": {
            "prediction": 0,
            "prediction_name": "好",
            "prediction_en": "good",
            "probabilities": {"good": 0.82, "usable": 0.15, "poor": 0.03},
        },
    }
    parsed = parse_upstream(payload)
    assert parsed["quality"] == "good"
    assert parsed["confidence"] == 0.82
    assert parsed["model_name"] == "Image_quality"
    assert parsed["probabilities"]["poor"] == 0.03


def test_parse_upstream_poor_is_ungradable_path():
    payload = {
        "result": {"prediction_en": "poor",
                   "probabilities": {"good": 0.05, "usable": 0.2, "poor": 0.75}},
    }
    parsed = parse_upstream(payload)
    assert parsed["quality"] == "poor"
    assert parsed["confidence"] == 0.75


@pytest.mark.parametrize("payload", [
    {}, None, {"result": {}}, {"result": {"probabilities": None}},
    {"result": {"prediction_en": "good", "probabilities": "坏数据"}},
])
def test_parse_upstream_is_fault_tolerant(payload):
    """
    上游字段缺失或结构变化时不得抛异常。
    整个门控应退化为「未评估」，而不是让阅片页崩掉。
    """
    parsed = parse_upstream(payload)
    assert "quality" in parsed
    assert isinstance(parsed["confidence"], float)


def test_parse_upstream_unknown_when_no_prediction():
    parsed = parse_upstream({"result": {"probabilities": {"good": 0.9}}})
    assert parsed["quality"] == "unknown", "没有预测类别时不能当作合格"


def test_parse_upstream_live_quality_level_fields():
    """线上接口用 quality_level_en / quality_name，不是 prediction_*。"""
    payload = {
        "model": {"name": "Image_quality", "task_type": "眼底图像质量评估"},
        "result": {
            "quality_level": 2,
            "quality_name": "差",
            "quality_level_en": "poor",
            "probabilities": {"good": 0.01, "usable": 0.2, "poor": 0.79},
        },
    }
    parsed = parse_upstream(payload)
    assert parsed["quality"] == "poor"
    assert parsed["confidence"] == 0.79


# --------------------------------------------------------------------------
# 质量进入安全元数据
# --------------------------------------------------------------------------

def test_quality_map_feeds_meta():
    images = [FakeImage(1), FakeImage(2, eye="OS")]
    qmap = {1: FakeQuality("good", 0.91), 2: FakeQuality("poor", 0.77)}
    meta = build_image_meta(records=images, quality_map=qmap)

    assert meta[0]["quality"] == "good"
    assert meta[0]["qualityText"] == "优质"
    assert meta[0]["ungradable"] is False

    assert meta[1]["quality"] == "poor"
    assert meta[1]["qualityText"] == "较差"
    assert meta[1]["ungradable"] is True
    assert meta[1]["qualityConfidence"] == 0.77


def test_missing_quality_is_unevaluated_not_good():
    """没有质量记录的影像必须是「未评估」，绝不能默认合格"""
    meta = build_image_meta(records=[FakeImage(1)], quality_map={})
    assert meta[0]["quality"] == "unknown"
    assert meta[0]["qualityText"] == "未评估"
    assert meta[0]["ungradable"] is False


def test_summary_flags_ungradable_case():
    images = [FakeImage(1), FakeImage(2, eye="OS")]
    qmap = {1: FakeQuality("good"), 2: FakeQuality("ungradable")}
    s = summarize_safety(build_image_meta(records=images, quality_map=qmap))

    assert s["hasUngradable"] is True
    assert s["ungradableCount"] == 1
    assert s["unevaluatedCount"] == 0
    assert s["qualityChecked"] is True


def test_summary_reports_partial_evaluation():
    """只评了一部分时，qualityChecked 必须为 False —— 不能显示成已完成质控"""
    images = [FakeImage(1), FakeImage(2, eye="OS")]
    qmap = {1: FakeQuality("good")}
    s = summarize_safety(build_image_meta(records=images, quality_map=qmap))

    assert s["unevaluatedCount"] == 1
    assert s["qualityChecked"] is False
    assert s["hasUngradable"] is False


def test_derived_objects_excluded_from_quality_summary():
    """派生对象（mask / overlay）不参与质量统计，只评原始影像"""
    images = [
        FakeImage(1, role="original"),
        FakeImage(2, role="MA"),
        FakeImage(3, role="overlay"),
    ]
    qmap = {1: FakeQuality("good")}
    s = summarize_safety(build_image_meta(records=images, quality_map=qmap))

    assert s["originalCount"] == 1
    assert s["derivedCount"] == 2
    assert s["qualityChecked"] is True, "原图已全部评估即视为质控完成"


def test_empty_case_is_not_quality_checked():
    """没有原始影像时不能报告「已质控」"""
    s = summarize_safety([])
    assert s["qualityChecked"] is False


def test_evaluate_case_auto_registers_legacy_image_paths(monkeypatch):
    """
    当病例仅有 image_paths 且 biz_case_image 尚无记录时，
    评估质量应自动将其实体化为 CaseImage(role='original') 并顺利完成评估，
    而不能报错报空。
    """
    import asyncio
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.base import Base
    from app.db.models import CaseImage, CaseImageQuality, Role, TrainingCase, User
    from app.services.image_quality_service import ImageQualityService
    from app.services import csu_eyes_client

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    try:
        role = Role(code="TEACHER", name="教师")
        session.add(role)
        session.flush()
        user = User(username="teacher", password_hash="x", role_id=role.id, real_name="老师")
        session.add(user)
        session.flush()

        case = TrainingCase(
            case_no="T-TEST-001",
            title="测试病例",
            creator_id=user.id,
            image_paths={"OS": ["/static/demo/fundus_normal_01.jpg"]},
        )
        session.add(case)
        session.commit()
        session.refresh(case)

        # 验证初始状态：biz_case_image 为空
        assert session.query(CaseImage).filter(CaseImage.case_id == case.id).count() == 0

        # Mock 算法评估
        async def fake_assess(image_path):
            return {
                "model": {"name": "TestModel"},
                "result": {
                    "prediction_en": "good",
                    "probabilities": {"good": 0.92, "usable": 0.08},
                },
            }
        monkeypatch.setattr(csu_eyes_client, "assess_image_quality", fake_assess)

        res = asyncio.run(ImageQualityService.evaluate_case(session, case.id))

        assert res["total"] == 1
        assert res["evaluated"] == 1
        assert res["failed"] == 0
        assert res["items"][0]["quality"] == "good"

        # 验证 CaseImage 已自动补齐登记
        ci = session.query(CaseImage).filter(
            CaseImage.case_table == "training",
            CaseImage.case_id == case.id,
            CaseImage.role == "original",
        ).first()
        assert ci is not None
        assert ci.eye == "OS"
        assert ci.file_url == "/static/demo/fundus_normal_01.jpg"

        # 验证 CaseImageQuality 已关联
        q = session.query(CaseImageQuality).filter(CaseImageQuality.case_image_id == ci.id).first()
        assert q is not None
        assert q.quality == "good"
    finally:
        session.close()


def test_evaluate_case_returns_zero_when_truly_no_images():
    """当病例确实没有任何影像路径时，明确返回 total=0"""
    import asyncio
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.base import Base
    from app.db.models import Role, TrainingCase, User
    from app.services.image_quality_service import ImageQualityService

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    try:
        role = Role(code="TEACHER", name="教师")
        session.add(role)
        session.flush()
        user = User(username="teacher", password_hash="x", role_id=role.id, real_name="老师")
        session.add(user)
        session.flush()

        case = TrainingCase(
            case_no="T-EMPTY-001",
            title="无图病例",
            creator_id=user.id,
            image_paths={},
        )
        session.add(case)
        session.commit()
        session.refresh(case)

        res = asyncio.run(ImageQualityService.evaluate_case(session, case.id))
        assert res["total"] == 0
        assert res["evaluated"] == 0
        assert res["items"] == []
    finally:
        session.close()



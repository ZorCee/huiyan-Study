"""受检者信息默认值 + MA 缺失不显示为 0。"""
from app.services.diagnosis_service import (
    AUTO_SUBJECT_PREFIX,
    display_subject_name,
    extract_ma_count,
    normalize_subject,
)


def test_subject_not_provided_defaults_to_unknown():
    s = normalize_subject(None, None, None)
    assert not s.provided
    assert s.subject_code == ""
    assert s.gender == "U"
    assert s.age is None


def test_subject_provided_is_kept():
    s = normalize_subject("  SC-001 ", "f", 56)
    assert s.provided
    assert s.subject_code == "SC-001"
    assert s.gender == "F"
    assert s.age == 56


def test_subject_invalid_values_fall_back():
    s = normalize_subject("x" * 50, "Z", 999)
    assert len(s.subject_code) == 32
    assert s.gender == "U"
    assert s.age is None


def test_display_auto_code_unchanged_and_legacy_name_masked():
    assert display_subject_name(f"{AUTO_SUBJECT_PREFIX}0007") == f"{AUTO_SUBJECT_PREFIX}0007"
    assert display_subject_name("夏宏伟") == "夏**"
    assert display_subject_name("夏军") == "夏*"
    assert display_subject_name("") == ""


def test_ma_missing_returns_none_not_zero():
    assert extract_ma_count(None) is None
    assert extract_ma_count({}) is None
    assert extract_ma_count({"status": "ok", "overlay_base64": "..."}) is None


def test_ma_real_zero_is_zero():
    assert extract_ma_count({"ma_count": 0}) == 0


def test_ma_single_endpoint_shape():
    assert extract_ma_count({"result": {"ma_count": 7}}) == 7
    assert extract_ma_count({"detections": [{}, {}, {}]}) == 3


def test_ma_comprehensive_per_eye_shape_takes_max():
    block = {"left_eye": {"ma_count": 2}, "right_eye": {"ma_count": 5}}
    assert extract_ma_count(block) == 5

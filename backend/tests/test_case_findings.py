# -*- coding: utf-8 -*-
"""
多病种结论与分级来源

- 人工 > 数据集 > AI；AI 不覆盖人工
- 冲突提示：人工 vs AI、标题 vs 金标准
- 历史病例无结论行时按 gold_dr_grade 读取，且能补数据
- 金标准弹窗保存 DR 结论时写回 gold_dr_grade
- AI 未返回分级时不冒充 0 级
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import CaseFinding, Role, RoleEnum, TrainingCase, User
from app.schemas.case_browse import FindingIn, GoldStandardUpdate
from app.services import case_findings
from app.services.case_browse_service import CaseBrowseService
from app.services.training_ai_service import _grade_opt


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def seeded(db):
    role = Role(code=RoleEnum.TEACHER.value, name="带教医师")
    db.add(role)
    db.flush()
    teacher = User(username="t", password_hash="x", role_id=role.id)
    db.add(teacher)
    db.flush()
    case = TrainingCase(
        case_no="T2026F01", title="DR 4级", category="DR",
        gold_dr_grade="0", gold_diagnosis="", teaching_points="",
        pass_score=60, is_published=False, is_train_case=False,
        creator_id=teacher.id,
    )
    db.add(case)
    db.commit()
    db.refresh(case)
    return {"teacher": teacher, "case": case}


def test_grade_opt_does_not_fake_zero():
    assert _grade_opt(None) is None
    assert _grade_opt("") is None
    assert _grade_opt("abc") is None
    assert _grade_opt("9") is None
    assert _grade_opt("0") == 0
    assert _grade_opt(3.0) == 3


@pytest.mark.parametrize("title,grade", [
    ("DR 4级", "4"), ("dr3级", "3"), ("2 级 DR", "2"),
    ("重度 NPDR", "3"), ("中度NPDR", "2"), ("PDR 伴新生血管", "4"),
    ("IDRiD_12 · 轻度 NPDR", "1"), ("青光眼病例", None), ("", None),
])
def test_title_dr_grade(title, grade):
    assert case_findings.title_dr_grade(title) == grade


def test_resolve_manual_wins():
    assert case_findings.resolve("4", "0") == ("4", "MANUAL")
    assert case_findings.resolve("", "0") == ("0", "AI")
    assert case_findings.resolve("", None) == (None, "AI")


def test_ai_does_not_overwrite_manual(db, seeded):
    cid = seeded["case"].id
    case_findings.upsert(db, cid, "DR", value="4", source="MANUAL", ai_value="0")
    case_findings.upsert(db, cid, "DR", value="1", source="AI")
    db.commit()
    row = db.query(CaseFinding).filter_by(case_id=cid, disease="DR").one()
    assert row.value == "4" and row.source == "MANUAL" and row.ai_value == "1"


def test_conflicts_manual_vs_ai_and_title(db, seeded):
    case = seeded["case"]
    case_findings.upsert(db, case.id, "DR", value="0", source="AI", ai_value="0")
    case_findings.upsert(db, case.id, "GLAUCOMA", value="1", source="MANUAL", ai_value="0")
    db.commit()
    msgs = case_findings.conflicts(case_findings.list_findings(db, case), case.title)
    assert any("青光眼" in m and "AI" in m for m in msgs)
    assert any("标题写的是 DR 4 级" in m for m in msgs)


def test_legacy_case_reads_and_backfills(db, seeded):
    case = seeded["case"]
    f = case_findings.list_findings(db, case)
    assert f[0]["disease"] == "DR" and f[0]["source"] == "DATASET" and f[0]["value"] == "0"
    assert case_findings.backfill_dr_findings(db) == 1
    assert case_findings.backfill_dr_findings(db) == 0


def test_gold_update_writes_back_and_keeps_ai(db, seeded):
    case, teacher = seeded["case"], seeded["teacher"]
    case_findings.upsert(db, case.id, "DR", value="0", source="AI", ai_value="0")
    db.commit()
    CaseBrowseService.update_gold_standard(
        db, teacher, case.id,
        GoldStandardUpdate(findings=[
            FindingIn(disease="DR", value="4"),
            FindingIn(disease="GLAUCOMA", value="S"),
        ]),
    )
    db.refresh(case)
    assert case.gold_dr_grade == "4"
    dr = db.query(CaseFinding).filter_by(case_id=case.id, disease="DR").one()
    assert dr.source == "MANUAL" and dr.ai_value == "0" and dr.confirmed_by == teacher.id
    gl = db.query(CaseFinding).filter_by(case_id=case.id, disease="GLAUCOMA").one()
    assert gl.value == "S"


def test_gold_update_rejects_bad_value(db, seeded):
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        CaseBrowseService.update_gold_standard(
            db, seeded["teacher"], seeded["case"].id,
            GoldStandardUpdate(findings=[FindingIn(disease="DR", value="7")]),
        )


def test_publish_confirms_ai_findings(db, seeded):
    case, teacher = seeded["case"], seeded["teacher"]
    case.gold_diagnosis = "4 级 PDR"
    case_findings.upsert(db, case.id, "DR", value="4", source="AI", ai_value="4")
    db.commit()
    CaseBrowseService.update_gold_standard(
        db, teacher, case.id, GoldStandardUpdate(publish=True),
    )
    row = db.query(CaseFinding).filter_by(case_id=case.id, disease="DR").one()
    assert row.source == "MANUAL"

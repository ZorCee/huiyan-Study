# -*- coding: utf-8 -*-
"""
多病种结论与分级来源。

优先级：人工（MANUAL） > 数据集/标题（DATASET） > AI 预测（AI，待复核）。
AI 结果只作建议，不会覆盖人工或数据集来源的结论。
新增病种只需在 DISEASES 里加一项。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.models.case_finding import CaseFinding

DISEASES: Dict[str, dict] = {
    "DR": {
        "label": "糖尿病视网膜病变",
        "options": [
            {"value": "0", "label": "0 级 无 DR"},
            {"value": "1", "label": "1 级 轻度 NPDR"},
            {"value": "2", "label": "2 级 中度 NPDR"},
            {"value": "3", "label": "3 级 重度 NPDR"},
            {"value": "4", "label": "4 级 PDR"},
        ],
    },
    "GLAUCOMA": {
        "label": "青光眼",
        "options": [
            {"value": "0", "label": "无"},
            {"value": "1", "label": "有"},
            {"value": "S", "label": "疑似"},
        ],
    },
}

SOURCES = ("MANUAL", "DATASET", "AI")
_RANK = {"MANUAL": 3, "DATASET": 2, "AI": 1}


def valid_value(disease: str, value: str) -> bool:
    cfg = DISEASES.get(disease)
    return bool(cfg) and value in {o["value"] for o in cfg["options"]}


def value_label(disease: str, value: Optional[str]) -> str:
    cfg = DISEASES.get(disease) or {}
    for o in cfg.get("options", []):
        if o["value"] == value:
            return o["label"]
    return ""


_TITLE_PATTERNS = [
    (re.compile(r"PDR|增殖期|增殖性"), "4"),
    (re.compile(r"重度\s*NPDR"), "3"),
    (re.compile(r"中度\s*NPDR"), "2"),
    (re.compile(r"轻度\s*NPDR"), "1"),
    (re.compile(r"无\s*DR|正常眼底"), "0"),
]
_TITLE_GRADE = re.compile(r"DR\s*([0-4])\s*级|([0-4])\s*级\s*DR", re.I)


def title_dr_grade(title: str) -> Optional[str]:
    """标题里明显写了 DR 分级时取出来，只用于冲突提示，不写入结论。"""
    text = (title or "").strip()
    if not text:
        return None
    m = _TITLE_GRADE.search(text)
    if m:
        return m.group(1) or m.group(2)
    upper = text.upper()
    # 先排除 NPDR，避免被 PDR 规则误中
    for pattern, grade in _TITLE_PATTERNS[1:]:
        if pattern.search(upper):
            return grade
    if _TITLE_PATTERNS[0][0].search(upper.replace("NPDR", "")):
        return "4"
    return None


def resolve(manual: Optional[str], ai: Optional[str]) -> tuple[Optional[str], str]:
    """建案时决定写入的值和来源：人工填写优先，否则用 AI。"""
    if manual not in (None, ""):
        return manual, "MANUAL"
    return ai, "AI"


def upsert(
    db: Session,
    case_id: int,
    disease: str,
    *,
    value: Optional[str],
    source: str,
    ai_value: Optional[str] = None,
    keep_ai: bool = False,
    confirmed_by: Optional[int] = None,
) -> Optional[CaseFinding]:
    row = (
        db.query(CaseFinding)
        .filter(CaseFinding.case_id == case_id, CaseFinding.disease == disease)
        .first()
    )
    if value in (None, ""):
        if row is not None:
            db.delete(row)
        return None
    if row is None:
        row = CaseFinding(case_id=case_id, disease=disease)
        db.add(row)
    elif source == "AI" and _RANK.get(row.source, 0) > _RANK["AI"]:
        # AI 不覆盖人工/数据集来源，只更新建议值
        row.ai_value = ai_value if ai_value is not None else value
        return row
    row.value = value
    row.source = source
    if not keep_ai:
        row.ai_value = ai_value
    if confirmed_by is not None:
        row.confirmed_by = confirmed_by
        row.confirmed_at = datetime.now()
    return row


def list_findings(db: Session, case) -> List[dict]:
    rows = (
        db.query(CaseFinding)
        .filter(CaseFinding.case_id == case.id)
        .order_by(CaseFinding.id.asc())
        .all()
    )
    out = [
        {
            "disease": r.disease,
            "disease_label": (DISEASES.get(r.disease) or {}).get("label", r.disease),
            "value": r.value,
            "value_label": value_label(r.disease, r.value),
            "source": r.source,
            "ai_value": r.ai_value,
            "ai_value_label": value_label(r.disease, r.ai_value) if r.ai_value else "",
            "confirmed": r.confirmed_at is not None,
        }
        for r in rows
    ]
    grade = (getattr(case, "gold_dr_grade", "") or "").strip()
    if not any(f["disease"] == "DR" for f in out) and grade.isdigit():
        # 历史病例没有结论行：按 gold_dr_grade 视为数据集来源
        out.insert(0, {
            "disease": "DR",
            "disease_label": DISEASES["DR"]["label"],
            "value": grade,
            "value_label": value_label("DR", grade),
            "source": "DATASET",
            "ai_value": None,
            "ai_value_label": "",
            "confirmed": False,
        })
    return out


def case_diseases(db: Session, case) -> List[str]:
    """病例实际涉及的病种（主病种在前）。"""
    primary = ((getattr(case, "category", "") or "DR").upper())
    found = [f["disease"] for f in list_findings(db, case) if f["value"] not in ("", "0")]
    out = [primary]
    for d in found:
        if d not in out:
            out.append(d)
    return out


def conflicts(findings: List[dict], title: str = "") -> List[str]:
    out: List[str] = []
    for f in findings:
        ai = f.get("ai_value")
        if ai not in (None, "") and f["source"] != "AI" and ai != f["value"]:
            out.append(
                f"{f['disease_label']}：{_src_text(f['source'])} {f['value_label']} / AI {f['ai_value_label'] or ai}"
            )
    dr = next((f for f in findings if f["disease"] == "DR"), None)
    t_grade = title_dr_grade(title)
    if dr and t_grade is not None and t_grade != dr["value"]:
        out.append(f"标题写的是 DR {t_grade} 级，但金标准是 {dr['value_label']}")
    return out


def _src_text(source: str) -> str:
    return {"MANUAL": "人工", "DATASET": "数据集", "AI": "AI"}.get(source, source)


def backfill_dr_findings(db: Session) -> int:
    """给历史病例按 gold_dr_grade 补一条 DR 结论（来源 DATASET），幂等。"""
    from app.db.models import TrainingCase

    have = {cid for (cid,) in db.query(CaseFinding.case_id).filter(CaseFinding.disease == "DR")}
    added = 0
    for case in db.query(TrainingCase).all():
        grade = (case.gold_dr_grade or "").strip()
        if case.id in have or not grade.isdigit():
            continue
        db.add(CaseFinding(case_id=case.id, disease="DR", value=grade, source="DATASET"))
        added += 1
    if added:
        db.commit()
    return added


def _disease_case_ids(db: Session, disease: str):
    """有该病种阳性结论的病例 id 子查询。DR 的 0 级也算 DR 病例（与原 category 语义一致）。"""
    disease = (disease or "").upper()
    q = db.query(CaseFinding.case_id).filter(CaseFinding.disease == disease, CaseFinding.value != "")
    if disease != "DR":
        q = q.filter(CaseFinding.value != "0")
    return q


def disease_clause(db: Session, disease: str):
    """列表/题库筛选条件：主病种是它，或结论表里有它。"""
    from sqlalchemy import or_

    from app.db.models import TrainingCase

    disease = (disease or "").upper()
    return or_(TrainingCase.category == disease, TrainingCase.id.in_(_disease_case_ids(db, disease)))


def case_ids_with_disease(db: Session, disease: str) -> set:
    return {cid for (cid,) in _disease_case_ids(db, disease)}


def has_disease(case, disease: str, finding_ids: set) -> bool:
    return (getattr(case, "category", "") or "").upper() == (disease or "").upper() or case.id in finding_ids

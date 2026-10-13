# -*- coding: utf-8 -*-
"""第 2 项 逐图题 / 挖空题。本对话未改动这部分，按验收标准测当前代码。"""

import pytest
from fastapi import HTTPException

from app.services.question_service import GUIDELINE_TEMPLATES, QuestionService

from .conftest import make_case


def test_r2_01_image_question_binds_image(db, people):
    """R2-01 | 医生为具体图像新建逐图题
    前置: 老师账号，一个脱敏病例
    步骤: 提交逐图题，带 case_id、image_url、ROI 框、关联标注
    预期: 创建成功，题型 IMAGE_LEVEL，图像与 ROI、关联标注都保存
    """
    case = make_case(db, people["teacher"], "REG-Q-1")
    q = QuestionService.create_question(db, people["teacher"], {
        "question_type": "IMAGE_LEVEL", "case_id": case.id,
        "image_url": "/static/demo/fundus_dr2_01.jpg",
        "stem": "图中颞上方箭头所指的红色点状病灶最可能是什么？",
        "answer": "微动脉瘤", "roi_box": {"x": 120, "y": 340, "w": 60, "h": 60},
        "related_annotation_id": "GOLD_1", "tags": ["DR"], "difficulty": "EASY",
        "explanation": "边界清楚的小红点", "source_guideline": "测试指南",
    })
    assert q.question_type == "IMAGE_LEVEL"
    assert q.image_url and q.roi_box and q.related_annotation_id == "GOLD_1"


def test_r2_02_image_question_requires_binding(db, people):
    """R2-02 | 逐图题未绑定图像被拒绝
    前置: 老师账号
    步骤: 提交不带 case_id / image_id / image_url 的逐图题
    预期: HTTP 400
    """
    with pytest.raises(HTTPException) as denied:
        QuestionService.create_question(db, people["teacher"], {
            "question_type": "IMAGE_LEVEL", "stem": "没有绑定图像的逐图题题干", "answer": "x",
        })
    assert denied.value.status_code == 400


def test_r2_03_guideline_blank_has_answer_and_source(db, people):
    """R2-03 | 按指南生成挖空题，带答案、解析、来源章节
    前置: 系统内置指南模板
    步骤: 用第一个模板生成挖空题
    预期: 题型 GUIDELINE_BLANK；题干含 {{blank_n}}；答案、解析、指南名、章节、挖空配置都非空
    """
    tpl = GUIDELINE_TEMPLATES[0]
    q = QuestionService.generate_from_template(db, people["teacher"], tpl["code"])
    assert q.question_type == "GUIDELINE_BLANK"
    assert "{{blank_" in q.stem
    for field in ("answer", "explanation", "source_guideline", "source_section"):
        assert getattr(q, field), f"{field} 为空"
    assert q.blank_config


def test_r2_04_duplicate_is_blocked(db, people):
    """R2-04 | 重复题目被去重规则拦截
    前置: 已用某模板生成一道挖空题
    步骤: 再次用同一模板生成；另提交仅标点不同的逐图题
    预期: 两次都返回 HTTP 400，提示"高度相似"
    """
    case = make_case(db, people["teacher"], "REG-Q-2")
    QuestionService.generate_from_template(db, people["teacher"], GUIDELINE_TEMPLATES[0]["code"])
    with pytest.raises(HTTPException) as again:
        QuestionService.generate_from_template(db, people["teacher"], GUIDELINE_TEMPLATES[0]["code"])
    assert again.value.status_code == 400 and "相似" in again.value.detail
    base = {"question_type": "IMAGE_LEVEL", "case_id": case.id, "answer": "出血"}
    QuestionService.create_question(db, people["teacher"], {**base, "stem": "图中黄斑区下方的片状红色区域是什么病灶"})
    with pytest.raises(HTTPException) as dup:
        QuestionService.create_question(db, people["teacher"], {**base, "stem": "图中，黄斑区下方的片状红色区域是什么病灶？"})
    assert dup.value.status_code == 400


def test_r2_05_templates_have_full_metadata():
    """R2-05 | 题目元信息完整（考点 / 难度 / 来源）
    前置: 系统内置指南模板列表
    步骤: 逐个检查模板字段
    预期: 每个模板都有 tags、difficulty、guideline、section、answer、explanation
    """
    assert GUIDELINE_TEMPLATES
    for tpl in GUIDELINE_TEMPLATES:
        for key in ("tags", "difficulty", "guideline", "section", "answer", "explanation"):
            assert tpl.get(key), f"{tpl.get('code')} 缺少 {key}"


def test_r2_06_student_cannot_create(db, people):
    """R2-06 | 学员无出题权限
    前置: 学员账号
    步骤: 提交逐图题
    预期: HTTP 403
    """
    with pytest.raises(HTTPException) as denied:
        QuestionService.create_question(db, people["student"], {
            "question_type": "IMAGE_LEVEL", "image_url": "/x.jpg", "stem": "学员尝试出题题干", "answer": "x",
        })
    assert denied.value.status_code == 403

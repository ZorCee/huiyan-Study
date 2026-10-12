"""
题库与题目生成服务 (QuestionService)
- 支持逐图出题（强绑定 imageId 与病灶标注 ROI）
- 支持基于临床指南/分级标准的自动挖空题生成
- 题干文本相似度去重拦截
- 挖空题模糊匹配评判
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from app.db.models.case_image import CaseImage
from app.db.models.question import Question, QuestionTypeEnum
from app.db.models.training_case import TrainingCase
from app.db.models.user import User, RoleEnum


# ==============================================================================
# 临床指南权威考点知识模板库
# 遵循《我国糖尿病视网膜病变临床诊疗指南(2022年)》与眼底病临床规范
# ==============================================================================
GUIDELINE_TEMPLATES: List[Dict[str, Any]] = [
    {
        "code": "DR_421_RULE",
        "title": "重度 NPDR 诊断依据（4-2-1 原则）",
        "guideline": "我国糖尿病视网膜病变临床诊疗指南(2022年)",
        "section": "第三部分·临床分级·表2 非增殖期分级标准",
        "tags": ["DR", "重度NPDR", "4-2-1原则", "静脉串珠", "IRMA"],
        "stem": "根据我国指南，重度 NPDR（3级）的“4-2-1 原则”要求在无新生血管前提下，满足以下任一条件：4 个象限均有明显出血；或至少在 {{blank_1}} 个象限出现明显静脉串珠；或至少在 {{blank_2}} 个象限出现明确的视网膜内微血管异常（IRMA）。",
        "blank_config": [
            {"index": 1, "key": "vein_quadrants", "label": "静脉串珠象限数", "expected": "2", "weight": 0.5},
            {"index": 2, "key": "irma_quadrants", "label": "IRMA象限数", "expected": "1", "weight": 0.5},
        ],
        "accept_alternatives": [
            ["2", "2个", "两个", "两", "至少2个"],
            ["1", "1个", "一个", "一", "至少1个"],
        ],
        "answer": "2 / 1",
        "difficulty": "MEDIUM",
        "explanation": "4-2-1 口诀：4象限多量视网膜内出血、2象限静脉串珠、1象限IRMA。具备其中任何一项且无新生血管，即诊断为重度 NPDR。",
    },
    {
        "code": "DR_GRADE_1",
        "title": "轻度 NPDR 核心体征",
        "guideline": "我国糖尿病视网膜病变临床诊疗指南(2022年)",
        "section": "第三部分·临床分级·轻度NPDR定义",
        "tags": ["DR", "轻度NPDR", "微动脉瘤"],
        "stem": "根据指南分级标准，轻度非增殖性糖尿病视网膜病变（轻度 NPDR）在眼底彩照上的唯一特征性标志病变是 {{blank_1}}，且不伴有视网膜出血、硬性渗出或软性渗出。",
        "blank_config": [
            {"index": 1, "key": "lesion_name", "label": "特征病变名称", "expected": "微动脉瘤", "weight": 1.0},
        ],
        "accept_alternatives": [
            ["微动脉瘤", "微血管瘤", "MA", "microaneurysm"],
        ],
        "answer": "微动脉瘤",
        "difficulty": "EASY",
        "explanation": "1 级轻度 NPDR 仅有微动脉瘤；一旦出现视网膜内出血、硬性渗出或棉绒斑，即进入 2 级中度 NPDR。",
    },
    {
        "code": "DR_PDR_HALLMARK",
        "title": "增殖期糖尿病视网膜病变（PDR）金标准依据",
        "guideline": "我国糖尿病视网膜病变临床诊疗指南(2022年)",
        "section": "第三部分·临床分级·PDR增殖期标准",
        "tags": ["DR", "PDR", "新生血管", "NVD", "NVE"],
        "stem": "从非增殖期（NPDR）进展为增殖期（PDR）的最关键分水岭体征是出现视盘或视盘外 {{blank_1}}，或由此引发的玻璃体积血、视网膜前出血及纤维增生。",
        "blank_config": [
            {"index": 1, "key": "pdr_hallmark", "label": "核心增殖体征", "expected": "新生血管", "weight": 1.0},
        ],
        "accept_alternatives": [
            ["新生血管", "视网膜新生血管", "NVD", "NVE", "neovascularization"],
        ],
        "answer": "新生血管",
        "difficulty": "EASY",
        "explanation": "没有新生血管及其并发症（玻璃体积血等），绝不能定为 PDR。视盘新生血管称为 NVD，视盘以外视网膜新生血管称为 NVE。",
    },
    {
        "code": "DR_CSME_DEFINITION",
        "title": "临床显著性黄斑水肿（CSME）判定",
        "guideline": "我国糖尿病视网膜病变临床诊疗指南(2022年)",
        "section": "第四部分·糖尿病黄斑水肿(DME)·CSME诊断",
        "tags": ["DME", "CSME", "硬性渗出", "黄斑中心凹"],
        "stem": "早期治疗糖尿病视网膜病变研究（ETDRS）定义的临床显著性黄斑水肿（CSME）标准中，当硬性渗出位于黄斑中心凹 {{blank_1}} 微米以内且伴邻近视网膜增厚时，即可确诊。",
        "blank_config": [
            {"index": 1, "key": "csme_distance", "label": "中心凹距离阈值", "expected": "500", "weight": 1.0},
        ],
        "accept_alternatives": [
            ["500", "500微米", "500μm", "500 um"],
        ],
        "answer": "500",
        "difficulty": "HARD",
        "explanation": "CSME 诊断条件之一：硬性渗出距离黄斑中心凹中心 ≤ 500 μm，且合并周围视网膜增厚。",
    },
    {
        "code": "GLAUCOMA_CD_RATIO",
        "title": "青光眼特征性视盘杯盘比（C/D）评估",
        "guideline": "我国原发性青光眼诊疗专家共识",
        "section": "视神经结构损害评估·视盘C/D比",
        "tags": ["青光眼", "视神经", "杯盘比", "C/D比"],
        "stem": "眼底照相评估青光眼性视神经病变时，通常将垂直方向视杯与视盘直径比（C/D 比）大于 {{blank_1}} 或两眼垂直 C/D 比差值大于 0.2 作为可疑青光眼的重要线索。",
        "blank_config": [
            {"index": 1, "key": "cd_threshold", "label": "垂直C/D比阈值", "expected": "0.6", "weight": 1.0},
        ],
        "accept_alternatives": [
            ["0.6", "0.60", "0.7"],
        ],
        "answer": "0.6",
        "difficulty": "MEDIUM",
        "explanation": "正常人群生理性大视杯垂直 C/D 多小于 0.6。垂直 C/D ≥ 0.6 或双眼 C/D 差值 ≥ 0.2 是青光眼筛查的重要指征。",
    },
]


class QuestionService:

    @staticmethod
    def _clean_text(s: str) -> str:
        """去除标点符号与空白字符，提取纯净对比字串"""
        return re.sub(r"[\s\.,;!?，。；！？、“”\"'’（）()\{\}]+", "", s.lower())

    @classmethod
    def calculate_similarity(cls, text_a: str, text_b: str) -> float:
        """计算两段题干的文本相似度（结合编辑距离与字符重合度）"""
        clean_a = cls._clean_text(text_a)
        clean_b = cls._clean_text(text_b)
        if not clean_a or not clean_b:
            return 0.0
        matcher = difflib.SequenceMatcher(None, clean_a, clean_b)
        return matcher.ratio()

    @classmethod
    def check_duplicate(
        cls, db: Session, stem: str, case_id: Optional[int] = None, exclude_id: Optional[int] = None
    ) -> Optional[Tuple[Question, float]]:
        """
        查重校验：检查题库中是否存在相似度超过 85% 的题干
        返回: (相似题目对象, 相似度得分) 或 None
        """
        q = db.query(Question).filter(Question.is_active == True)  # noqa: E712
        if exclude_id:
            q = q.filter(Question.id != exclude_id)
        if case_id:
            # 优先在同一病例内查重，再在全局指南题中查重
            q = q.filter(or_(Question.case_id == case_id, Question.case_id.is_(None)))

        candidates: List[Question] = q.all()
        for cand in candidates:
            sim = cls.calculate_similarity(stem, cand.stem)
            if sim >= 0.85:
                return cand, round(sim * 100, 1)
        return None

    @classmethod
    def create_question(cls, db: Session, user: User, data: Dict[str, Any]) -> Question:
        """
        创建新题目（医生端出题接口）
        - 校验逐图题是否绑定有效病例与图像
        - 校验题干查重
        """
        role_code = user.role.code if user.role else None
        is_teacher = role_code in (RoleEnum.TEACHER.value, RoleEnum.ADMIN.value)
        if not is_teacher:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="仅带教医师或管理员拥有出题权限",
            )

        q_type = data.get("question_type") or QuestionTypeEnum.IMAGE_LEVEL
        stem = (data.get("stem") or "").strip()
        if not stem:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="题干内容不能为空")

        case_id = data.get("case_id")
        # 查重校验
        dup = cls.check_duplicate(db, stem, case_id=case_id)
        if dup:
            existing, sim_val = dup
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"检测到高度相似题目（已存在题目 #{existing.id}，相似度 {sim_val}%），请勿重复创建",
            )

        # 逐图题校验
        image_id = data.get("image_id")
        image_url = data.get("image_url")
        if q_type == QuestionTypeEnum.IMAGE_LEVEL:
            if not image_url and not image_id and not case_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="逐图题必须绑定具体的影像文件 (image_id / image_url)",
                )

        # 挖空题解析与验证
        blank_config = data.get("blank_config") or []
        if q_type == QuestionTypeEnum.GUIDELINE_BLANK and not blank_config:
            # 自动从题干中的 {{blank_n}} 提取占位符
            blanks = re.findall(r"\{\{blank_(\d+)\}\}", stem)
            if not blanks:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="指南挖空题必须在题干中包含至少一个挖空占位符（格式如 {{blank_1}}）",
                )

        q = Question(
            question_type=q_type,
            case_id=case_id,
            image_id=image_id,
            image_url=image_url,
            stem=stem,
            options=data.get("options") or None,
            answer=(data.get("answer") or "").strip(),
            accept_alternatives=data.get("accept_alternatives") or None,
            blank_config=blank_config or None,
            related_annotation_id=data.get("related_annotation_id"),
            roi_box=data.get("roi_box"),
            source_guideline=data.get("source_guideline"),
            source_section=data.get("source_section"),
            tags=data.get("tags") or [],
            difficulty=data.get("difficulty") or "MEDIUM",
            explanation=data.get("explanation") or "",
            created_by=user.id,
            is_active=True,
        )
        db.add(q)
        db.commit()
        db.refresh(q)
        return q

    @classmethod
    def list_guideline_templates(cls) -> List[Dict[str, Any]]:
        """获取系统内置的权威临床指南考点模板列表"""
        return GUIDELINE_TEMPLATES

    @classmethod
    def generate_from_template(
        cls, db: Session, user: User, template_code: str, case_id: Optional[int] = None
    ) -> Question:
        """根据指定指南考点模板快速生成一道标准化挖空题"""
        tpl = next((t for t in GUIDELINE_TEMPLATES if t["code"] == template_code), None)
        if not tpl:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"未找到指定的指南模板：{template_code}",
            )

        data = {
            "question_type": QuestionTypeEnum.GUIDELINE_BLANK,
            "case_id": case_id,
            "stem": tpl["stem"],
            "options": None,
            "answer": tpl["answer"],
            "accept_alternatives": tpl["accept_alternatives"],
            "blank_config": tpl["blank_config"],
            "source_guideline": tpl["guideline"],
            "source_section": tpl["section"],
            "tags": tpl["tags"],
            "difficulty": tpl["difficulty"],
            "explanation": tpl["explanation"],
        }
        return cls.create_question(db, user, data)

    @classmethod
    def get_questions_for_case(
        cls, db: Session, case_id: int, image_url: Optional[str] = None
    ) -> List[Question]:
        """获取属于该病例的专属逐图题以及通用指南挖空题"""
        # 1. 查该病例绑定的逐图题
        q = (
            db.query(Question)
            .filter(Question.case_id == case_id, Question.is_active == True)  # noqa: E712
            .order_by(desc(Question.id))
        )
        questions = q.all()

        # 2. 如果当前病例缺少专属题目，按病种与指南补齐通用题目
        if len(questions) < 4:
            case = db.query(TrainingCase).filter(TrainingCase.id == case_id).first()
            cat = case.category if case else "DR"
            generics = (
                db.query(Question)
                .filter(
                    Question.case_id.is_(None),
                    Question.is_active == True,  # noqa: E712
                )
                .order_by(Question.id.asc())
                .limit(4 - len(questions))
                .all()
            )
            questions.extend(generics)

        return questions

    @classmethod
    def grade_answer(cls, question: Question, student_answer: str) -> Tuple[bool, float, str]:
        """
        题目判分算法
        - 选择题：完全一致判对
        - 挖空题：支持分空打分与同义词容错（accept_alternatives）
        返回: (是否完全正确, 得分率 0.0~1.0, 评分说明)
        """
        clean_ans = (student_answer or "").strip()
        if not clean_ans:
            return False, 0.0, "未作答"

        # 选择题与简答题
        if question.question_type in (QuestionTypeEnum.IMAGE_LEVEL, QuestionTypeEnum.CHOICE):
            expected = (question.answer or "").strip()
            # 选项首字母容错，如学生输入 "A" 与答案 "A. 微动脉瘤" 匹配
            if clean_ans == expected:
                return True, 1.0, "回答正确"
            if len(clean_ans) == 1 and expected.startswith(clean_ans.upper()):
                return True, 1.0, "回答正确"
            # 同义词容错
            alts = question.accept_alternatives or []
            if any(clean_ans.lower() == str(alt).lower() for alt in alts):
                return True, 1.0, "回答正确（同义词匹配）"
            return False, 0.0, f"回答错误，标准答案：{expected}"

        # 挖空题（多空分项打分）
        if question.question_type == QuestionTypeEnum.GUIDELINE_BLANK:
            config = question.blank_config or []
            alts_list = question.accept_alternatives or []
            if not config:
                # 单空回退
                expected = (question.answer or "").strip()
                if clean_ans.lower() == expected.lower():
                    return True, 1.0, "回答正确"
                for alt_group in alts_list:
                    if isinstance(alt_group, list) and any(clean_ans.lower() == str(a).lower() for a in alt_group):
                        return True, 1.0, "回答正确"
                return False, 0.0, f"回答错误，标准答案：{expected}"

            # 多空按斜杠、逗号或分号拆分用户输入
            user_parts = [p.strip() for p in re.split(r"[/,;，；、]+", clean_ans) if p.strip()]
            total_weight = sum(float(c.get("weight", 1.0)) for c in config) or 1.0
            earned_weight = 0.0

            for idx, c in enumerate(config):
                expected = str(c.get("expected", "")).strip().lower()
                weight = float(c.get("weight", 1.0))
                user_val = user_parts[idx].lower() if idx < len(user_parts) else ""

                match_ok = (user_val == expected)
                if not match_ok and idx < len(alts_list):
                    alt_candidates = alts_list[idx]
                    if isinstance(alt_candidates, list):
                        match_ok = any(user_val == str(a).lower() for a in alt_candidates)

                if match_ok:
                    earned_weight += weight

            ratio = round(earned_weight / total_weight, 2)
            is_full = (ratio >= 0.99)
            return is_full, ratio, f"得分率 {int(ratio * 100)}%"

        return False, 0.0, "未知题型"

    @classmethod
    def seed_default_questions(cls, db: Session) -> int:
        """数据库初始化：当题库为空时自动灌注典型逐图题与指南挖空题"""
        count = db.query(Question).count()
        if count > 0:
            return 0

        created_cnt = 0
        # 1. 灌注经典指南挖空题
        for tpl in GUIDELINE_TEMPLATES:
            q = Question(
                question_type=QuestionTypeEnum.GUIDELINE_BLANK,
                case_id=None,
                stem=tpl["stem"],
                options=None,
                answer=tpl["answer"],
                accept_alternatives=tpl["accept_alternatives"],
                blank_config=tpl["blank_config"],
                source_guideline=tpl["guideline"],
                source_section=tpl["section"],
                tags=tpl["tags"],
                difficulty=tpl["difficulty"],
                explanation=tpl["explanation"],
                is_active=True,
            )
            db.add(q)
            created_cnt += 1

        # 2. 为 IDRiD 经典病例绑定逐图题
        # IDRiD-T-IDRiD_04 (ID=92)
        c4 = db.query(TrainingCase).filter(TrainingCase.case_no == "IDRID-T-IDRiD_04").first()
        if c4:
            q_img = Question(
                question_type=QuestionTypeEnum.IMAGE_LEVEL,
                case_id=c4.id,
                image_url="/static/training/idrid/original/IDRiD_04.jpg",
                stem="在本张眼底彩照（IDRiD_04）中，黄斑颞下方可见多枚散在微小红点及斑片状暗红病灶（标示区），下列哪项符合该眼底特征？",
                options=[
                    "A. 仅见微动脉瘤，属于轻度 NPDR",
                    "B. 可见明确微动脉瘤与出血斑，属于中度 NPDR",
                    "C. 出现大量新生血管，已进展为 PDR",
                    "D. 视网膜未见任何糖尿病微血管病变",
                ],
                answer="B. 可见明确微动脉瘤与出血斑，属于中度 NPDR",
                accept_alternatives=["B", "b", "中度 NPDR"],
                related_annotation_id="GOLD_1",
                roi_box={"x": 550, "y": 620, "w": 120, "h": 120},
                source_guideline="我国糖尿病视网膜病变临床诊疗指南(2022年)",
                source_section="第三部分·临床分级·中度NPDR判定",
                tags=["IDRiD_04", "微动脉瘤", "出血斑", "中度NPDR"],
                difficulty="MEDIUM",
                explanation="IDRiD_04 病例中包含微动脉瘤（MA: 804像素）和大量视网膜内出血（HE: 59383像素），超出 1 级标准，且未达到 4-2-1 原则与新生血管，确诊为 2 级中度 NPDR。",
                is_active=True,
            )
            db.add(q_img)
            created_cnt += 1

        db.commit()
        return created_cnt

# 慧眼医学教学实训平台 · 版本更新记录 (Changelog)

本文档记录了平台自纳入 Git 版本管理以来的所有版本迭代内容与改动详情。

> **术语说明（教师端入口）**
> - **图像质控**：评估眼底原图的可用性（好 / 可用 / 差、清晰度、曝光、视盘覆盖），作用对象是图像，不评学员。入口在阅片工作台顶部「图像质控」「查看质控结果」按钮。
> - **作业批阅**：审核学员提交的阅片诊断作业和图像质控作业，给出通过或驳回。入口在左栏「作业批阅」，地址为 `/training/reading?tab=review`（旧地址 `tab=quality`、`/training/review` 自动跳转）。
> - 文档或旧代码中的「质量评估」「影像质量评估」统一指图像质控；作业类型值 `QUALITY` 保持不变。

## [v5.1] - 2026-10-14

### 🎯 版本概述
**全链路临床规范白皮书落地、阅片算法双抽屉扩展、学情四层下钻与 28 项全业务回归测试验收**。本版本全面完善了平台的临床教学白皮书与技术规范矩阵，扩展了阅片工作站的 AI 算法分析与图像质控详情双抽屉面板；全新上线学情分析四层下钻中枢（KPI 穿透、学员明细抽屉、弱项病例弹窗）；打通 28 项跨端核心修改点并完成 100% 自动化回归测试验收（包含完整测试验收报告与界面截图存档）。

### ✨ 新增与重构 (Added / Refactored)
- **学情分析四层下钻与错题穿透 (`KpiDrilldownDialog.vue` / `StudentDrilldownDrawer.vue` / `WeakCaseListDialog.vue` / `test_r28_r29_drilldown.py`)**：
  - 教师端首页大盘指标支持点击深度下钻，实现“班级汇总 → 学员完成度明细 → 专项弱项病例列表 → 阅片工作站金标准对比”四层无缝穿透；
  - 规范带教组分组筛选与状态机联动，支持组间数据隔离与跨组快速切换。
- **28 项全业务修改点统一自动化测试验收 (`backend/reports/regression/*`)**：
  - 构建覆盖 28 项修改点（#1~#29）共 65 项用例的自动化测试工程，自动化跑测通过率 100%；
  - 产出标准化测试验收报告 (`report.md`) 及 8 张主要页面深浅色高精度验收截图 (`shots/`) 随版本归档。
- **业务自动化回归测试矩阵 (`backend/tests/regression/*` / `frontend/scripts/regression/*`)**：
  - 新增回归测试套件（R2 影像题库、R3/R5 静态资源加载、R6 正式考试准入、R9 金标准只读与越权防护、R10 待审核计数校验、R11 筛查统计口径、R28/R29 学情下钻）；
  - 新增前端端到端回归自动化脚本 `frontend/scripts/regression/e2e.mjs` 及后端报告生成器 `build_report.py`。
- **临床教学规范与技术白皮书矩阵 (`docs/*`)**：
  - 新增《AI筛查统计口径》、《AI算法调用矩阵》、《受检者信息字段说明》、《图像质控与建案门控说明》、《多病种与分级来源说明》、《推荐病例数据来源说明》、《教学分享与学生端联动说明》、《教师演示病例与公共学习资料区分说明》、《教师端信息架构》、《数据可见范围说明》与《题库标准化调研》11 篇深度文档。
- **阅片与教学工作站交互升级 (`frontend/src/views/reading/*` / `learning/*`)**：
  - 新增 `AiAlgorithmDrawer.vue`（AI 辅助判读算法分析抽屉）与 `ImageQualityResultDrawer.vue`（图像质控多维度详情抽屉）；
  - 新增 `admin-notes.vue`（管理员端教学笔记与学习资料管理面板）；
  - 引入 `usePendingReviewCount` 与 `useInboxSignals` 响应式状态管理，实时联动教师端待审核数与未读通知角标。
- **病灶标注与影像规范升级 (`case_finding.py` / `case-findings.ts` / `lesion-colors.ts`)**：
  - 规范化病灶标注类型与高对比度色卡呈现，打通标注点位与题库挖空点位双向联动。
- **本地便捷运维脚本 (`scripts/start_local.bat` / `scripts/stop_local.bat`)**：
  - 补齐一键启动前后端与一键终止本地环境脚本。

---

## [v4.5] - 2026-10-12

### 🎯 版本概述
**影像题库与图像质量门控双引擎上线、阅片/实习工作站综合重构**。本版本围绕"评估有效性"主线，新引入按图绑定的临床影像题库系统与基于 CSU-EYES 模型的图像质量门控；同时对阅片工作站与学员实训工作站进行大尺度重构，正式落地多病灶分割服务接入、把质量门控作为强前置、把题目生成嵌入阅片侧栏等关键能力。

### ✨ 新增功能 (Added)
- **影像题库系统全新模块（题目全链路：生成 / 存储 / 出题 / 评判）**：
  - **后端模型与 API**：
    - 新增 `backend/app/db/models/question.py`（`Question` / `QuestionTypeEnum`）与 `backend/app/schemas/question.py`（题干/作答 Pydantic 模型）；
    - 新增 `backend/app/api/v1/question.py` 路由接口；
    - 新增 `backend/app/services/question_service.py` —— 题库与题目生成服务，能力：
      - 支持**逐图出题**（强绑定 `imageId` 与病灶标注 ROI，确保题目与影像一一对应）；
      - 内置**临床指南权威考点知识模板库**（遵循《我国糖尿病视网膜病变临床诊疗指南(2022 年)》等眼底病规范），可基于指南/分级标准**自动挖空题生成**；
      - 题干文本相似度去重拦截，防止雷同题污染题库；
      - 挖空题**模糊匹配评判**，支持等价答案容错（如 "2 / 2 个 / 至少 2 个" 视为一致）。
  - **前端集成与 UI**：
    - 新增 `frontend/src/api/question.ts` 题库 API 客户端；
    - 新增 `frontend/src/views/reading/components/ImageQuestionDrawer.vue` —— 阅片侧栏**图像题目抽屉**，阅片过程中无缝弹出对应图片的临床题目；
    - 新增 `frontend/src/components/CaseSelect.vue` 通用病例选择器组件，支持阅片/题库/分享多场景复用。
- **图像质量门控服务（先质量后诊断）**：
  - 新增 `backend/app/services/image_quality_service.py`：
    - 复用平台已上线的 CSU-EYES ConvNeXt 图像质量三分类模型（`good / usable / poor / ungradable`），**不训练新模型**；
    - 派生对象 `biz_case_image_quality` 与原始影像记录解耦，质量变化不污染影像主档；
    - 实现"**先质量后诊断**"规则：图像未加载、眼别冲突或质量不可判读时，**绝不默认判为正常**；
    - **降级而非阻断**：算法服务不可用时降级为"未评估"并记录原因，避免单点阻塞。
  - 新增 `backend/tests/test_image_quality_gate.py`（116 行 pytest）—— 覆盖 `normalize_quality` / `parse_upstream` / 图像元数据构建与汇总等关键路径。
  - 集成入口：在 `backend/app/main.py` 注册质量门控相关路由/`startup` 钩子，`backend/app/api/v1/router.py` 暴露对外接口。
- **多病灶分割服务升级 (`backend/app/services/lesion_seg_service.py` +115)**：扩展多病灶并行推理管线，对接新增的题库校验与病灶 ROI 标注双向反馈链路。
- **影像笔记编辑对话框重做 (`NoteEditDialog.vue` +58)**：支持在笔记内嵌病灶引用、影像题引用与质控标注，结构化字段满足教学复盘。

### 🔨 重构与优化 (Changed / Refactored)
- **阅片工作站重大重构 (`frontend/src/views/reading/index.vue` +442)**：
  - 重写主页视图骨架，把影像渲染、AI 诊断对比、质控面板、题目抽屉、评审侧栏拆为可单独维护子模块；
  - `frontend/src/views/reading/components/ReadingSidePanel.vue` (+58) 重组侧栏交互，顶部新增"图像题目 / 质控状态 / AI 比对 / 快捷评语胶囊"多 Tab；
  - `ReadingQualityPanel.vue` / `ReadingReviewDialog.vue` 联调质控面板与评审对话框，质控结果作为前置门禁生效。
  - 新增/扩展 `frontend/src/components/CoreRetinaStation.vue` (+145) 核心视网膜渲染组件，作为阅片、学员实训、技师工作站统一的影像渲染底座。
- **学员实训工作站重构 (`frontend/src/views/practice/workstation.vue` +178 / `backend/app/services/practice_service.py` +268)**：
  - 后端 `practice_service.py` 大尺度重构：固化"图像质量门控 → 题目解锁 → 作答 → 评判 → 归档"完整流水线；
  - `backend/app/api/v1/practice.py` 同步调整接口契约；
  - 前端 `workstation.vue` 适配新流水线，加载流程显示门控状态、题目抽屉与 AI 评注联动。
- **病例影像一对多结构化 (`backend/app/services/case_image_service.py` +97)**：补全"同一病例多影像分组/角色(OD/OS/原图/标注图)"维护路径，配合题库与质控使用。
- **病例浏览中枢继续精简 (`backend/app/services/case_browse_service.py` -27)**：配合教师端 v4.4 精简路线，删除重复的影像聚合分支，瘦身接口字段。
- **辅助工具与渲染引擎适配**：
  - `frontend/src/utils/cornerstone3d.ts` (+18) —— 适配新版 `CoreRetinaStation` 的视口重置与坐标系同步；
  - `frontend/src/utils/finding-locate.ts` 病灶定位工具修正叠加层坐标系。
- **培训/教学侧轻量化适配**：
  - `backend/app/services/training_service.py` (+21) 配套接入影像题库；
  - `backend/app/services/teaching_service.py` / `reading_service.py` 同步接口小幅补全；
  - `backend/app/db/models/__init__.py` (+1) 导出新 `Question` 模型。

### 🛡️ 安全 / 仓库治理 (Repo Hygiene)
- `.gitignore` 增加 `scratch/` 目录排除（用于放未成形/一次性调试脚本，正式测试请使用 `backend/tests/` 下 pytest 体系）；
- `*.tar.gz` 早已在 `.gitignore` 中，发布整包不会误入库；
- 已在 `main` / `dev` / `v4-local` 三条分支同 `HEAD` 上完成 `v4.5` 提交，并打 `v4.5` tag 推送至 GitHub。

---

## [v4.4] - 2026-09-28

### 🎯 版本概述
**综合修复（精简教师端功能与界面）**。针对临床带教老师使用痛点，深度重构并精简教师端交互架构与视觉呈现，收拢冗余菜单层级，重构病例库浏览中枢，升级阅片批改评语胶囊与流水线作业批注体验，大幅降低教师使用认知负荷。

### ✨ 新增与精简重构 (Added / Refactored)
- **教师端菜单与架构精简 (`TrainingPortal.vue` / `router/index.ts`)**：
  - 深度精简侧边栏层级与选项，剔除分散繁琐的入口，聚焦核心教学业务场景；
  - 优化移动端/不同分辨率下的布局响应度与暗色模式变量。
- **病例浏览中枢解耦重构 (`CaseBrowseWorkspace.vue` / `views/case-browse/index.vue`)**：
  - 抽离独立的工作区组件 `CaseBrowseWorkspace.vue`，实现病例列表、筛选检索与影像卡片的模块化解耦，大幅瘦身主页面。
- **阅片批改体验升级与快捷评语胶囊 (`ReadingSidePanel.vue` / `ReviewPresetChips.vue` / `reading/index.vue`)**：
  - 引入高频预置评语胶囊（`ReviewPresetChips.vue`），支持一键点击填入典型病灶诊断意见；
  - 重构批阅侧栏面板交互，突出关键扣分项、AI 比对与金标准快速复核。
- **教师首页与教学管理收敛 (`home.vue` / `class-students.vue` / `exams.vue`)**：
  - 优化规培轮转大盘展示，简化班级学生信息维护流程，提升正式考试列表与防作弊组卷交互。
- **实训作答提交守卫与工作站交互优化 (`submit-guard.ts` / `practice/workstation.vue` / `practice/index.vue`)**：
  - 增加学员提交前的完整性校验与防呆守卫，优化做题进度提示与成绩回填联动。

---

## [v4.3] - 2026-09-24

### 🎯 版本概述
**管理端整改与教学分享范围升级**。本版本全面重构并完善了平台管理后台的多项核心中枢能力（科室院区权限隔离、用户管理中枢、带教入库审核、IDRiD 数据集导入管理），并扩展升级了“病例分享至学员实训”的分享范围机制，全面支持按年级、轮转批次、带教组或学员个体精准分发。

### ✨ 新增与重构 (Added / Refactored)
- **管理端中枢深度整改 (`views/admin/sections/*`)**：
  - **科室与院区管理 (`DepartmentsSection.vue` / `test_department_hospital_scope.py`)**：完善科室层级与所属院区数据隔离；
  - **用户与权限管理 (`UsersSection.vue` / `admin_user_service.py` / `admin-users.ts`)**：支持更严密的角色分配、密码重置与部门归属管理；
  - **带教入库审核流 (`TeachingReviewSection.vue` / `test_teaching_review_approve.py`)**：优化病例入库审核、一键发布及驳回提示机制；
  - **数据集管理 (`IdridImportSection.vue` / `idrid_import_service.py`)**：修复并稳定 IDRiD 批量数据集导入流水线。
- **教学病例分享范围扩展 (`ShareDialog.vue` / `models/teaching_share.py` / `teaching_service.py` / `test_teaching_share_scope.py`)**：
  - 打破原先仅支持“全体学员”的限制，新增**指定年级 (`YEAR`)**、**指定轮转批次 (`BATCH`)**、**指定带教组 (`GROUP`)** 以及**指定具体学员 (`PEOPLE`)** 多级筛选模式；
  - 支持组内一键勾选“全部”或按姓名点选学员，学员端仅可见自身所在班级/组别的分享病例。
- **阅片安全与工作站工具提升 (`CoreRetinaStation.vue` / `ReadingSafetyBar.vue` / `CaseIdPair.vue`)**：
  - 增强影像安全校验与脱敏呈现，对齐工作站工具栏及各门户（培训/筛查/患者）主题配色。

---

## [v4.2] - 2026-09-23

### 🎯 版本概述
**教师端功能全量版（未精简版）**。本版本完整集成了面向眼科带教老师的全套教学工具链，包括正式考试管理系统、班级分组与学员进度大盘、教学大纲指引体系、病例批量导入工具与全链路多角色测试覆盖。

### ✨ 新增功能 (Added)
- **正式考试系统 (`exams.vue` / `exam.py` / `models/exam_paper.py` / `services/exam_service.py`)**：
  - 完整支持正式考核试卷创建、自选/随机抽题组卷、考试倒计时与答题防作弊限制；
  - 自动打分与试卷提交评定记录归档。
- **班级学生与带教分组管理 (`class-students.vue` / `services/rotation_service.py`)**：
  - 支持按年级、轮转批次、带教组批量维护规培学员信息并动态计算组别进度。
- **教学大纲指引视图 (`TeachingOutlineView.vue` / `utils/teaching-outline.ts`)**：
  - 结构化展示规培教学要点与眼底病种分类考核指引。
- **病例批量导入工具 (`CaseBatchImportDialog.vue` / `services/case_import_service.py`)**：
  - 支持带教老师与管理员批量导入眼底影像与标注数据。
- **全链路自动化测试扩展**：
  - 新增正式考试流程测试 (`test_formal_exam.py`)、病灶多维度评分测试 (`test_lesion_scoring.py`)、质控与审核联动测试 (`test_quality_review_link.py`)、教学答案脱敏测试 (`test_teaching_hide_answers.py`) 等。

### 🔨 优化与调整 (Changed / Fixed)
- **教师首页学员大盘优化 (`home.vue`)**：
  - 完善全班练习次数、完成病例、平均成绩与学时统计，支持多维度组别过滤与错题统计。
- **审核链路归拢与重构**：
  - 废弃冗余的独立待审入口，将作业批改流对齐到工作台与管理后台。
- **权限与数据一致性对齐**：
  - 强化教师端教学分享、演示病例查看与病例浏览中的权限判定与状态同步。

---

## [v4.1] - 2026-09-22

### 🎯 版本概述
本版本全面聚焦**学员端问题修复与规培实训体验升级**。针对规培学员临床实训反馈，修复阅片工作站交互与 AI 诊断/质控异常，新增轮转任务首页、理论知识自测体系、病灶定位引导及多样化笔记文档展示。

### ✨ 新增功能 (Added)
- **规培轮转实训首页 (`views/training/home.vue` / `rotation.py`)**：
  - 新增学员专属轮转学习任务大盘，支持展示今日学习任务、必做病例、轮转截止时间与达标进度追踪。
- **理论自测与综合题库 (`services/text_quiz.py` / `models/text_quiz_attempt.py`)**：
  - 补充理论文本试题考核体系，支持知识点选择、填空客观题自测与评测留痕。
- **病灶定位指引练习 (`utils/finding-locate.ts`)**：
  - 勾选征象（微动脉瘤、出血、渗出等）后引导学员在眼底图上指出至少一处典型位置。
- **富文本笔记与学习资料增强 (`NoteContentView.vue` / `utils/note-content.ts`)**：
  - 学习资料支持多样化笔记格式展示，优化未解析格式与资料文件的直接下载交互。

### 🔨 优化与修复 (Fixed / Changed)
- **阅片工作站交互深度修复 (`CoreRetinaStation.vue` / `ReadingToolbar.vue` / `DiagnosisForm.vue`)**：
  - 修复切换工具后恢复指针状态、金标准图层/原图/病灶标注图层切换不生效问题；
  - 修正做题评分与准确率指标语义，避免初始状态出现默认 DR 等级与误导性 100% 得分。
- **左右眼判定与显示修正 (`eye_infer.py` / `case_utils.py`)**：
  - 修正单张眼底图像误识别为双眼的问题，增强单侧眼别推断与数据库对齐能力。
- **AI 辅助诊断与影像质控容灾优化 (`csu_eyes_client.py` / `diagnosis_service.py` / `image_quality_service.py`)**：
  - 优化质控评估与 AI 诊断调用超时与失败降级策略，提供平滑友好提示。
- **自主练习与带教评审流解耦 (`practice_service.py` / `student-teaching.vue` / `student-reviews.vue`)**：
  - 区分自主练习与正式考核，优化练习自评闭环与演示病例教学步骤。

---

## [v4] - 2026-09-17

### 🎯 版本概述
全系统代码综合收敛与完善。重构并升级了**登录重要通知弹窗与未读管理**机制，统一了传统登录与 OIDC 单点登录的通知触发流程，完善了带教评审与消息中心全链路。

### ✨ 新增与重构 (Added / Refactored)
- **登录重要通知管理体系 (`login-notice.ts` / `LoginNoticeDialog.vue`)**：
  - 新增 `login-notice.ts` 工具模块，抽离登录通知判断、已读标记与防刷规则；
  - 重构登录提示弹窗 `LoginNoticeDialog.vue`，优化通知展示、多条通知翻页及“我已知晓”已读交互逻辑。
- **通知服务与状态同步 (`notice_service.py` / `schemas/common.py`)**：
  - 后端规范化通知数据契约，强化已读时间戳记录与未读数量查询性能。
- **统一身份接入链路对齐 (`login/index.vue` / `oidc-callback.vue`)**：
  - 对齐普通账号密码登录与 OIDC 单点登录（Keycloak）成功后的通知拉取流程，确保任何入口登录均能精确触发关键通知。
- **测试用例覆盖扩充 (`test_notice_read.py` / `test_teacher_review_list.py`)**：
  - 扩充测试用例，覆盖登录通知读取标记、幂等性防护与带教评审列表组合查询。

### 🔨 优化与微调 (Changed)
- 优化带教实训待审列表与质控面板细节交互；
- 更新用户状态管理（`stores/user.ts`）与门户导航（`TrainingPortal.vue`），提升组件通信稳定性。

---

## [v3] - 2026-09-17

### 🎯 版本概述
本版本重点针对**阅片工作站交互**、**带教评审闭环**以及**学员反馈体验**进行了深度优化与功能补齐。

### ✨ 新增功能 (Added)
- **阅片质控面板 (`ReadingQualityPanel.vue`)**：
  - 在阅片工作站中新增影像质控组件，提供眼底图像质量（清晰度、曝光、视盘覆盖度）的实时评估与合规指引。
- **带教评审弹窗 (`ReadingReviewDialog.vue`)**：
  - 为带教老师提供结构化批阅界面，支持评分、评语录入、典型病灶标注指引。
- **学员评审反馈页面 (`student-reviews.vue`)**：
  - 新增学员专属评审查看页，学员可查看历史实训报告的老师打分、批注及驳回修改建议。
- **自动化测试用例 (`test_teacher_review_list.py`)**：
  - 新增带教审核列表的后端单元测试，覆盖按状态筛选、权限���离等边界场景。

### 🔨 优化与修复 (Changed / Fixed)
- **实训状态机完善 (`reading_service.py` / `practice_service.py`)**：
  - 修复老师驳回后学员无法在同一记录上重新编辑提交的问题，实现“提交 ➔ 驳回 ➔ 重新提交”完整闭环。
- **阅片主工作台重构 (`reading/index.vue`)**：
  - 整合质控面板与审核弹窗，优化工具栏交互与标注图层切换响应速度。
- **个人中心与实训入口打通**：
  - 在个人中心增加最新评审提醒，实训列表支持高亮展示待整改报告。

---

## [v2] - 2026-09-16

### 🎯 版本概述
重大业务功能版本。新增完整的多角色用户管理中枢、学员自主注册审批流程、站内通知系统，并正式归档了全平台端到端业务流程图。

### ✨ 新增功能 (Added)
- **用户管理中枢 (`admin_users.py` / `UsersSection.vue`)**：
  - 管理后台新增用户管理列表，支持管理员进行账号的新增、编辑、禁用/启用、重置密码及部门角色分配。
- **学员自主注册与审核流 (`student_application.py` / `StudentApplicationsSection.vue`)**：
  - 新增学员申请注册入口（`apply-student.vue`）；
  - 管理后台新增学员审核列表，支持审核通过（自动开通账号并触发通知）或驳回。
- **短信通知集成 (`sms_service.py`)**：
  - 引入短信服务模块，支持在账号开通、重置密码时下发短信凭据。
- **站内通知中心 (`NotificationInbox.vue` / `LoginNoticeDialog.vue`)**：
  - 新增用户收件箱，支持系统广播与个人通知查看；
  - 登录时自动弹窗提醒重要未读消息，已读状态落库持久化。
- **端到端业务流程图 (`docs/慧眼平台-端到端业务流程图.drawio`)**：
  - 归档了全平台完整的视觉化业务流向图，涵盖影像接入、AI 辅助、学员阅片、带教考核全链路。

### 🗄️ 数据库变更 (Database Migrations)
- **迁移脚本 `0016_student_application_and_must_change_password.py`**：
  - 新建 `sys_student_application`（学员申请表）；
  - `sys_user` 表新增 `must_change_password` 字段，支持首次登录强制修改初始密码。

---

## [v1] - 2026-09-16

### 🎯 版本概述
平台基线版本（原始工程云端归档）。

### 📦 核心能力基线
- **前端工作站 (Vue 3 + TypeScript + Vite + Element Plus)**：
  - 基于 Cornerstone3D 的眼底高精度医学影像加载与画布交互（平移、缩放、多边形病灶标注、测量）；
  - AI 辅助诊断推理结果叠加展示；
  - 模拟患者档案与病例浏览中心。
- **后端架构 (FastAPI + SQLAlchemy + Alembic)**：
  - 统一认证鉴权（JWT / OAuth2 / OIDC Keycloak 对接）；
  - 完整的眼科病例管理、实训练习评分规则引擎；
  - 自动化测试套件（350+ 项单元测试与集成测试通过）。
- **工程化与部署 (Docker)**：
  - 规范化的 `.gitignore` 机制；
  - 具备 PACS (Orthanc) 影像归档与 Moodle LTI 1.3 教学平台集成基础。

---

*后续版本更新请遵循本规范持续向下追加。*

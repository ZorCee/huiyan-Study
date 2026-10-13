# AI 筛查统计口径

接口：`GET /screening/stats`（不带 `scope` 即全量口径，响应头 `Cache-Control: no-store`）
实现：`backend/app/services/screening_service.py` → `ScreeningService.stats`
前端：`frontend/src/views/screening/index.vue` 顶部统计卡片

| 卡片 | 口径 | 数据来源 |
|---|---|---|
| 累计筛查（按次） | 全部筛查记录数，每次 AI 判读计 1 次，**不按图片或患者去重**；完成后不会从统计中消失 | `biz_screening_case` 行数 |
| 高危 | 病例所有结果中最高风险为 `HIGH` 或 `URGENT` | `biz_screening_result.risk_level`，每个病例只计一次 |
| 中危 | 最高风险为 `MEDIUM` | 同上 |
| 正常 | 最高风险为 `LOW` | 同上 |
| 分析中 / 排队 | `status IN (PENDING, PROCESSING)` | `biz_screening_case.status` |
| 失败 | `status = FAILED` | 同上 |

说明：

- 高危 + 中危 + 正常 = 已有判读结果的病例数；处理中、失败的病例没有结果，只计入累计。
- 左右眼结果不同时按较高风险计一次，例如右眼高危、左眼正常，计入高危。
- 「分析任务队列」只显示未完成（排队、处理中、失败）的任务，和顶部累计的范围不同，所以两个数字不相等属于正常；卡片和队列标题都有悬停说明。
- 前端统计数字只取接口返回值，接口返回 0 时显示 0，不会用队列长度代替。

核对：`python backend/scripts/check_screening_stats.py`（只读）会用独立 SQL 重新计算一遍，与接口逐项比对，并列出卡在处理中或失败的记录；加 `--export x.csv` 参数可以导出备份。

回归测试：`backend/tests/regression/test_r11_screening_stats.py`。

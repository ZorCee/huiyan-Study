# AI算法调用矩阵（阅片页「AI算法判读」）

所有算法都在 CSU-EYES 算法服务器（`CSU_EYES_BASE_URL`）上运行。本系统后端只负责转发请求、保存叠加图，并把各算法的返回整理成统一格式，**不在后端容器里加载任何深度学习模型**。

| key | 名称 | 类型 | 模型 | CSU-EYES 接口 | 输入 | 输出 | 学员可见 | 当前状态 |
|---|---|---|---|---|---|---|---|---|
| `multi_lesion` | 多病灶分割 | 分割 | VMUNet（mamba_ssm，需 GPU） | `POST inference/multi-lesion-segmentation` | 眼底彩照 | EX / SE / HE 叠加图 + 各类像素数 | 是 | **未部署**，待杨总团队部署 |
| `ma_detection` | 微动脉瘤分割 | 分割 | UNet-EfficientNetB4 | `POST inference/ma-detection` | 眼底彩照 | MA 叠加图 + 数量 | 是 | 可用 |
| `ocod` | 视杯视盘分割 / 杯盘比 | 分割 | VMUnet OCOD | `POST inference/ocod-segmentation` | 眼底彩照 | 视杯视盘叠加图 + 垂直/水平杯盘比 + 风险等级 | 是 | 可用 |
| `glaucoma` | 青光眼判别 | 分类 | ConvNeXt-tiny | `POST inference/glaucoma-screening` | 眼底彩照 | 结论 + 各类概率 | **否，只给老师和管理员** | 可用 |

## 本系统接口

- `GET /api/v1/reading/ai-algorithms`：返回算法目录，以及根据 `/api/v1/models` 和接口探测得到的实时状态（可用 / 未部署 / 连不上）。学员拿到的目录里不含青光眼判别。
- `POST /api/v1/reading/cases/{id}/ai-run`，请求体 `{algorithm, imageUrl, eye?}`，统一返回：
  `{status, algorithm, algorithmName, kind, overlayUrl, counts, classification, metrics, seconds, message}`
  - `status = not_deployed`：算法服务器返回 404/405，说明对应接口尚未部署。
  - `status = failed`：调用超时、算法服务器报错等，`message` 里写明原因。
- 旧接口 `POST .../lesion-seg`、`POST .../ai-predict` 仍保留，内部改为调用上面的统一入口。

## 颜色表

叠加图图例使用 IDRiD 颜色，前端 `frontend/src/utils/lesion-colors.ts` 与后端 `ai_algorithm_service.LESION_COLORS` 共用同一套颜色，`backend/tests/test_ai_algorithms.py` 会比对两边是否一致。

| 标签 | 含义 | 颜色 |
|---|---|---|
| HE | 视网膜出血 | `#f53f3f` |
| EX | 硬性渗出 | `#ffd700` |
| SE | 软性渗出/棉绒斑 | `#52c41a` |
| MA | 微动脉瘤 | `#eb2f96` |
| OD | 视盘 | `#1677ff` |
| NV | 新生血管 | `#13c2c2` |

## 多病灶分割部署说明（交给算法服务器）

- 代码：`backend/vendor/multi_lesions_seg/`（仅作为部署参考，后端不再导入它）。
- 依赖：torch、scipy、einops、timm，以及需要 CUDA 编译的 `mamba_ssm`（见 `requirements-lesion.txt`）。
- 权重：`best_mdice.pth`，部署到算法服务器上，与 OCOD 模型共用 GPU 环境。部署前先在测试环境确认不会影响视杯视盘分割。
- 接口约定：`POST inference/multi-lesion-segmentation`，输入输出格式与 `ma-detection` 一致，返回 EX / SE / HE 的掩膜或叠加图。部署后，阅片页无需改代码即可显示为「可用」。

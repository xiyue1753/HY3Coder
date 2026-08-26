# 实现记录（逐任务确认）

> 本文件用于记录每个已完成任务的实现逻辑、输入/输出、调用文件，
> 供逐环节确认与讨论修改。每个任务按「目标 / 实现逻辑 / 输入输出 / 调用文件 / 验证」组织。

---

## 任务 env-fix：环境固化（conda tensor_env）

**状态**：✅ 已完成

### 目标
项目此前用错解释器（系统 python 是 WindowsApps stub，调用报 exit 9009；旧文档写 anaconda base Python 3.13）。本次改为锁定 conda 虚拟环境 `tensor_env`，固化调用方式，杜绝用错。

### 实现逻辑
1. **选定环境**：`D:\.conda\envs\tensor_env\python.exe`（Python 3.9.24）。这是一个空 conda 环境，已执行 `pip install -r requirements.txt` 装入全部依赖。
2. **解决 3.9 兼容性**：代码使用 `X | None` 等 3.10+ 类型注解语法，在 Python 3.9 下运行时 pydantic 无法求值注解。通过安装 `eval_type_backport` 包解决（pydantic 在 3.9 下会自动用它对注解做后向求值）。
3. **新增 `run.ps1`**：统一入口脚本，硬编码 tensor_env 的 python 路径，提供 `test` / `run-eval` / `run-refine` / `report` / `serve` / `py` / `exec` 子命令，并支持环境变量 `REX_PYTHON` 覆盖。所有命令自动 `Set-Location` 到项目根。
4. **更新 `requirements.txt`**：加入 `eval_type_backport`，并把版本说明从"Python 3.13"改为"推荐 tensor_env（3.9），亦可 3.13"。
5. **更新 `README.md`**：环境要求章节说明系统 python 不可用、推荐 conda tensor_env、`run.ps1` 用法。

### 输入 / 输出
- 输入：无（纯环境/脚本/文档配置）
- 输出：
  - `run.ps1`（新文件）：统一运行脚本
  - `requirements.txt`（改）：+`eval_type_backport`
  - `README.md`（改）：环境与运行方式说明
  - `docs/IMPL_LOG.md`（新）：本记录

### 调用文件
- `run.ps1` → 调用 `D:\.conda\envs\tensor_env\python.exe`
- 依赖清单：`requirements.txt`

### 验证
- `.\run.ps1 test` → **34 passed**（全部测试在 tensor_env / Python 3.9 下通过）
- `tensor_env` 下 `pydantic 2.13.4`、`pytest 8.4.2`、`datasets 4.5.0` 均可用

---

## 任务 metric-caliber：过程评估指标口径对齐（定位准确率 / 误报率）

**状态**：✅ 已完成

### 目标
任务书 P4 要求"有效性验证"口径：
- **定位准确率**：在**答案错误的样本**上，评估器能否判定过程存在问题并定位到实际出错步骤
- **误报率**：在**答案正确的样本**上，被判过程有问题的样本经人工抽检确认真实/误报比例

原 `audit_metrics` 用"系统判定过程有错（PROCESS_INCORRECT/SILENT_FAILURE）"作统一分母，两者混算，与任务书不符。本次改为按"答案正确性（answer_correct）"划分两套独立分母。

### 实现逻辑
1. **重写 `audit_metrics`**（`src/rex/metrics/compute.py`）：
   - **定位准确率**：分母 = `answer_correct is False` 的样本（答案错误样本）；分子 = 其中系统判定过程有错（PROCESS_INCORRECT/SILENT_FAILURE）**且**人工标注的 `error_step_id` 被系统 findings 覆盖者。即衡量"答案错了时，评估器能否既判过程有错又定位对步骤"。
   - **误报率**：分母 = `answer_correct is True` 且被系统判过程有错的样本；分子 = 其中人工确认 `is_false_positive=True` 者。即衡量"答案对但被误判过程有错的样本中，多少是真误报"。
   - **答案正确性未知（`answer_correct is None`）** 的样本不进两个分母，但计入总样本数 `n`（可见性）。
2. **扩展 `AuditMetrics` dataclass**：新增 `localization_n`（定位准确率分母）和 `fp_n`（误报率分母），保留旧字段 `n`/`error_localization_hit_rate`/`false_positive_rate` 以兼容。
3. **更新 `make_report.py` §6 人工抽检**：报告标注两套分母及口径说明。

### 输入 / 输出
- 输入：`EvalRecord` 列表（含 `answer_correct`、`verification.verdict`、`findings`）+ 人工抽检对象列表（含 `question_id`/`error_step_id`/`is_false_positive`）
- 输出：`AuditMetrics`（含 `localization_n`/`error_localization_hit_rate`/`fp_n`/`false_positive_rate`/`n`）

### 调用文件
- 逻辑：`src/rex/metrics/compute.py` → `audit_metrics`、`AuditMetrics`
- 报告：`scripts/make_report.py` → §6 人工抽检
- 测试：`tests/test_metrics.py` → `test_audit_metrics_localization_and_fp`、`test_audit_metrics_answer_unknown_excluded`

### 验证
- `.\run.ps1 test` → **35 passed**（新增 2 个口径测试）
- `make_report.build()` → 正常生成
- lint 干净

---

## 任务 interact-demo：交互式解题页面展示力完善（计划外，用户临时插入）

**状态**：✅ 已完成

### 背景
用户希望先完成"应用侧"（任务书 demo 展示力）的完善，暂时搁置需依赖评估数据的 metric-caliber 验证。选定了"展示力完善"方向。

### 目标
增强仪表盘「交互式解题」页面：展示沙盒执行结果、错误步骤高亮、findings 定位、耗时/调用次数，使 demo 完整呈现"分步求解 → 沙盒执行 → 过程验证 → 错误定位"的完整链路。

### 实现逻辑
1. **后端 `api.py` `interact` 增强**：
   - 计时总耗时 `elapsed`（秒）
   - 返回模型调用次数 `cost_calls`（来自 `pipe.client.call_count`）
   - eval 模式下单独调用 `pipe._execute(q, rec.answer)` 拿沙盒执行细节 `exec: {test_pass_rate, error}`（测试通过率 + 运行错误，供前端展示算法场景的沙盒结果）
   - 新增 `import time`
2. **前端 `index.html` `interact()` 重写**：
   - 头部：判定标签 + 模式 + 耗时/调用次数
   - 沙盒执行结果：算法场景显示测试通过率（≥100% 绿色，否则黄色）+ 运行错误
   - 步骤卡片：按 `verification.findings` 的 `step_id` 给错误步骤加 `.err` 高亮，正确过程加 `.ok`
   - findings 定位列表：错误类型 + 步骤 + 详情（复用 `TYPE_CN`）
   - 无错误时显示"未检出过程错误 · 置信度"

### 输入 / 输出
- 输入：`POST /api/interact`（scene/prompt/answer/refine）
- 输出：JSON `{mode, eval|refine, elapsed, cost_calls, exec:{test_pass_rate, error}}`

### 调用文件
- 后端：`src/web/api.py` → `interact`
- 前端：`src/web/static/index.html` → `interact()` 函数

### 验证
- `api.py` 导入成功，`/api/interact` 路由注册正常
- 实际交互需 Hy3 key 调模型（演示时验证）

---

<!-- 后续任务按此格式追加 -->

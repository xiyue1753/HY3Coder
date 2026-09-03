# HY3Coder 设计文档（正式版）

面向可验证场景（算法竞赛）的**过程评估与错误定位 + 自我修正**系统。
本文件为正式设计文档，取代早期草案，包含分层规则表、错误分类体系、核心 schema 契约与双模式数据流说明。
（数学/MATH 评测路线已放弃，2026-09-03，本文档与代码同步移除 math 场景。）

---

## 1. 系统目标

给定一道算法竞赛题（含输入输出格式、数据范围与约束），系统产出**结构化分步求解过程**并自动评估：

1. **过程评估**：判定推理链是否成立（逐步自含性 + 全局回溯两轮审查）。
2. **错误定位**：定位错误起始步骤，并归纳错误类型。
3. **沉默失败识别**：识别"最终答案正确但过程无法支撑结论"的样本。
4. **自我修正（ReAct 闭环）**：验证反馈回流驱动求解 Agent 迭代修订，报告修正前后过程正确率对比。

## 2. 架构总览

```
data/questions（题集：公开算法对照 + 自建，三档分层）
        │  QuestionItem（题目/标准答案/测试用例/难度/来源/分层依据/判题模式）
        │  公开对照: algorithm.jsonl（TACO 350 活跃，CF 350 已 deprecated 弃用）
        │  自建:     abc_selfbuilt.jsonl（AtCoder ABC 175 题，独立产线见 §3）
        ▼
solver/  分步求解 Agent ──► Answer(steps[]+final_answer+code)
        │                     │
        │                     ├─► executor/  沙盒执行+公开/隐藏用例+静态检查+SPJ
        │                     │        （测试用例通过率；无用例时文本比对 standard_answer）
        ▼                     ▼
verifier/  验证 Agent×2（自含性检查+全局回溯）──► VerificationResult
        交叉复核不一致 → 仲裁 → 仍分歧标记 HUMAN_REVIEW
        │
        ├─ eval 模式（数据纯净）：结果写入 eval_{scene}.jsonl → metrics
        └─ refine 模式：findings → RefineFeedback → solver.revise → 重验证（≤3 轮）
               记录 RefineRound 轨迹 → refine_{scene}.jsonl（与 eval 严格分离）
        │
        ▼
metrics/  答案准确率/过程正确率/定位命中率/误报率/Wilson 区间/稳定性验证/修正前后对比
        ▼
web/ 仪表盘（总览/单题回放/golden/抽检/交互式解题）  ·  cli.py（run-eval/run-refine/audit/serve）
```

## 3. 数据集与分层规则

| 场景 | 来源 | 许可 | 入库 | 分层映射 | 分层依据 |
|---|---|---|---|---|---|
| 算法·公开对照 | TACO（agentica-org/DeepCoder-Preview-Dataset） | Apache-2.0 | 350 活跃 | difficulty∈{easy→basic, medium→medium, hard→hard} | 官方难度标签 |
| 算法·公开集(弃用) | CodeForces 镜像（同上源） | Apache-2.0 | 350 deprecated | — | 已标 metadata.deprecated，抽样/评测自动排除 |
| 算法·自建 | AtCoder ABC（scripts/ingest_abc.py 抓取） | 竞赛题（抓题面+公开 AC 解） | 175 | 官方分值 100→basic, 200-400→medium, 500+→hard | 官方分值 + layer_basis |

- 自建题产线（响应任务书"公开集为主 + 自建补充"）：
  `ingest_abc.py`（抓题面+AC 解）→ 官方样例 + 人工边界用例（gen_hidden_cases.py，期望由参考解跑出）→ `abc_selfbuilt.jsonl`；
  多解构造题以 `judge=special` 入库（SPJ checker，见 §5.5）。独立文件便于扩充，web/browse 合并展示；
  进入 run-eval 前需并入评估池（见 §10 数据流说明）。
- 分层抽样（`datasets/sampling.py`，自动过滤 deprecated）：

| --sample | 算法（basic/medium/hard） |
|---|---|
| 5 | 2/2/1 |
| 10 | 4/4/2 |
| 50 | 20/20/10 |
| 100 | 100/100/100 |
| full | 全部活跃（TACO 350 或并入自建后的池） |

- 抽样种子固定（默认 42），保证分档统计可复现。
- 每档实际抽样数 = min(档位需求, 池内数量)，池不足时按池兜底。

## 4. 核心 schema 契约（src/rex/models.py）

```python
class Step(BaseModel):
    id: int
    kind: Literal[                # 算法竞赛步骤类型
        "understand", "approach", "complexity", "implement", "selftest",
    ]
    content: str       # 步骤内容
    conclusion: str    # 步骤结论
    deps: list[int]    # 前置依赖步骤

class Answer(BaseModel):
    steps: list[Step]        # 非空
    final_answer: str
    code: str | None = None  # implement 步骤提取的完整代码

class ErrorFinding(BaseModel):
    step_id: int | None
    error_type: ErrorType
    detail: str
    evidence: str

class VerificationResult(BaseModel):
    verdict: Literal["CORRECT", "PROCESS_INCORRECT", "ANSWER_INCORRECT", "SILENT_FAILURE"]
    findings: list[ErrorFinding]
    confidence: float
    arbiter: Literal["V1", "V2", "ARBITER", "HUMAN_REVIEW"]
    timestamp: float

class RefineFeedback(BaseModel):
    step_id: int | None      # 定位
    error_type: ErrorType    # 归类
    instruction: str         # 可操作修订指令
    evidence: str

class RefineRound(BaseModel):
    round_no: int
    revised_answer: Answer
    feedbacks: list[RefineFeedback]
    verification: VerificationResult
    cost_calls: int

class EvalRecord(BaseModel):   # 数据纯净，绝不混入 refine 结果
    question_id, scene, difficulty, answer, answer_correct, test_pass_rate,
    verification, cost_calls, created_at

class RefineRecord(BaseModel):
    question_id, scene, difficulty, initial, rounds, final, converged, cost_calls, created_at
```

## 5. 错误分类体系（src/rex/verifier/errors.py）

| 层级 | 类型 | 说明 | 典型证据 |
|---|---|---|---|
| 6 类基线 | misread 题意误读 | 未正确理解题目条件 | 步骤结论与题目条件矛盾 |
| | concept 概念理解错误 | 定义/公式/定理误用 | 公式引用错误、概念名称误用 |
| | calculation 计算错误 | 数值/符号运算错误 | 代入、化简、运算结果不符 |
| | condition 条件遗漏 | 漏掉边界/分类/前提条件 | 未讨论 n=0、绝对值分情况等 |
| | jump 跳步推导 | 步骤结论无法由前文推出 | 依赖未出现的关键定理/步骤 |
| | format 格式不符 | 输出/表述不符合要求 | 要求多行输出单行等 |
| 场景扩展 | logic 逻辑缺陷 | 算法/推理逻辑结构错误 | 死循环、条件分支错误、循环论证 |
| | boundary 边界条件 | 输入边界处理缺失 | 除零、空输入、0 值特例 |
| | complexity 复杂度不达标 | 复杂度声明与实际不符 | 声明 O(n) 实际 O(n²)/O(2^n) |

## 5.5 算法判题模式（executor/judge.py：exact vs special/SPJ）

常规算法题输出唯一，判题用"期望文本比对"（`run_test_cases`，含浮点容差 1e-5）。
但**构造/多解题**（如输出任意合法操作序列）没有唯一期望文本——官方样例只是众多
合法解之一，与 AI 解文本不同不代表错误。这类题由 AtCoder/CF 用 **Special Judge** 判定。

本系统在 `QuestionItem` 上以 `judge` 字段区分两模式：

| judge | 含义 | 判题方式 |
|---|---|---|
| `exact`（默认） | 输出唯一 | 期望文本逐行比对 + 浮点容差 |
| `special` | 构造/多解 | 跑 checker 判定"输出满足题目谓词" |

- `checker_code`/`checker_language`：`special` 模式的判定程序（可信代码，Python/C++，
  由人工为题目编写）。stdin 协议见 `executor/judge.py`：`原题输入\n@@REX_USER_OUTPUT@@\n被测输出`，
  输出 `AC` 表示合法。
- 接入点：① 评测 `run_test_cases(judge=..., checker_code=...)` ② 入库
  `ingest_abc.py --judge special --checker-file ...`（此时自动找 AC 也用 checker 而非样例比对）。
- checker 运行仍走沙盒（继承超时/输出上限），不信任输入输出内容。

自建题 SPJ 清单（5 题，checker 在 `scripts/checkers/`）：
- A1031 abc271_d Flip and Adjust（Yes/No + H/T 方案，DP 可达判定 + 方案校验）
- A1072 abc315_e Prerequisites（输出依赖闭包的任意拓扑序）
- A1076 abc299_e Nearest Black Vertex（Yes/No + 涂色串，候选域可行性判定 + BFS 校验）
- A1103 abc216_c Many Balls（构造 A/B 操作序列到 N）
- A1104 abc251_d At Most 3（构造 ≤300 砝码覆盖 [1,W]）

存量扫描：algorithm.jsonl（公开集，已弃用标记）内 ~50 题命中 SPJ 特征词，
不在本次处理范围；abc_selfbuilt 内 A1098 abc228_d 的 "one such" 为误报（指查询存在）。

## 6. 验证流程（src/rex/verifier/）

1. **V1**：逐步自含性检查——每步 content 推导 conclusion 是否成立、deps 是否覆盖前置。
2. **V2**：全局回溯——从最终答案反向验证链条一致性，检查跳步/循环论证。
3. 双视角不一致 → 仲裁 Agent 判定；仍分歧 → `HUMAN_REVIEW`。
4. `findings` 携带 step_id 供定位与 refine 使用。

判定口径（`Verdict`）：
- `CORRECT`：过程与答案均成立。
- `PROCESS_INCORRECT`：过程有缺陷，答案可能仍对（含沉默失败）。
- `ANSWER_INCORRECT`：答案与标准答案不符（沙盒/比对为准）。
- `SILENT_FAILURE`：答案正确（沙盒/比对/步骤自含性均通过）但过程存在根本缺陷。

## 7. 双模式与数据纯净性

| 模式 | CLI | 数据流 | 输出 | 用途 |
|---|---|---|---|---|
| eval | `run-eval` | 一次性：solve→execute→verify，反馈绝不回流 | `data/outputs/eval_{scene}.jsonl` | 全部指标的**唯一**数据来源 |
| refine | `run-refine` | 循环：verify→feedback→revise→re-verify（≤3 轮） | `data/outputs/refine_{scene}.jsonl` | 修正效果对比（不计入 eval 指标） |

- 每轮修正记录 `RefineRound`（修订后答案+反馈+重验证），支持"修正前后对比"。
- 断点续跑：JSONL 追加写，重启跳过已完成 question_id。
- 成本核算：`Hy3Client.call_count` 每实际请求自增（含重试），逐轮/累计可查。

## 8. Golden 沉默失败样本（data/golden/）

人工构造 15 条（算法）"陷阱样本"：**答案正确但过程存在根本缺陷**，
用于验证评估器能否检出 `SILENT_FAILURE`，而非被正确答案误导。

| 构造手法 | 示例（算法） |
|---|---|
| 用例恰好覆盖不到 | 质数判定把 1 当质数但用例 n≥2；GCD 缺 b=0 终止但用例 b>0 |
| 数据范围内不触发 | 声明 O(n) 实为 O(n²)/O(2^n)，用例 n 恰好小 |
| 概念误用却得对 | set 无序却宣称保序；无序组合数碰巧等于有序计数 |
| 推理错误结果碰巧对 | 快排宣称稳定但输入无相等元素 |
| 格式与要求不符 | 要求多行输出单行（单元素用例碰巧同） |

每条含 `flaw_type`（真实缺陷类型）与 `construction_note`（构造说明），
供人工核验评估器检出率与定位精度。

## 9. 指标（src/rex/metrics/）

| 指标 | 定义 | 支撑 |
|---|---|---|
| 答案准确率 | 答案正确题目 / 总题 | 算法沙盒全过（无用例时文本比对） |
| 过程正确率 | verdict=CORRECT 题目 / 总题 | 验证 Agent×2+仲裁 |
| 错误定位命中率 | 系统定位 step 与人工标注 ≤1 步 / 答案错误抽检样本 | audit_records.jsonl |
| 误报率 | 答案正确但被判有错样本中人工确认为误报比例 | audit_records.jsonl |
| 沉默失败检出率 | golden 样本中判定 SILENT_FAILURE 比例 | golden 库 |
| 修正提升 | refine 前后过程正确率差 | refine_{scene}.jsonl |
| 置信区间 | Wilson interval（95%） | stats.py |
| 稳定性 | 同档二次抽样指标漂移 | stats.py |

## 10. 运行方式

```bash
# 环境（优先级：优先 tensor_env，其次 anaconda）
#   D:\.conda\envs\tensor_env\python.exe  (Python 3.9, 推荐, run.ps1 默认)
#   D:\ProgramData\anaconda3\python.exe   (Python 3.13, 备选)
#   .\run.ps1 ...  统一入口；或 $env:REX_PYTHON=... 覆盖解释器
# .env 提供 HY3_API_KEY / HY3_BASE_URL / HY3_MODEL

# 评估模式（数据纯净）
python -m src.cli run-eval --scene algorithm --sample 5        # demo
python -m src.cli run-eval --scene algorithm --sample 100      # 放大

# 自建题（AtCoder 175 题）跑评估：直接指定题集文件
python -m src.cli run-eval --questions abc_selfbuilt.jsonl --sample full --resume

# 修正模式（ReAct 闭环）
python -m src.cli run-refine --scene algorithm --sample 5 --max-rounds 3

# 答案校验 / 人工抽检 / 仪表盘
python -m src.cli check-answers --results data/outputs/eval_algorithm.jsonl
python -m src.cli audit --results data/outputs/eval_algorithm.jsonl --sample 30
python -m src.cli serve    # http://127.0.0.1:8000

# 测试
python -m pytest tests/
```

## 11. 交付物清单

- 源码（src/rex/ 模块化，tests/ pytest）
- 题集 data/questions/：
  - 公开对照：algorithm.jsonl（TACO 350 活跃 + CF 350 deprecated + 自编）
  - 自建：abc_selfbuilt.jsonl（AtCoder ABC 175 题，含参考解/用例/SPJ，按难度分层）
  - 均含标准答案/参考解、分层依据（layer_basis）
- Golden 样本库 data/golden/（golden_algorithm 15 条，含构造说明）
- 评估结果 data/outputs/（eval/refine 严格分离，可断点续跑）
- 分析报告 reports/（分层退化、错误分布、case 归因、修正前后对比、能力画像）
- 人工抽检记录 data/outputs/audit_records.jsonl
- Demo 视频脚本 reports/demo_script.md

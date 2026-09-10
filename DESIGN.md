# HY3Coder 设计文档（正式版）

面向可验证场景（算法竞赛）的**过程评估与错误定位 + 自我修正**系统。
本文件为正式设计文档：分层规则表、错误分类体系、核心 schema 契约、双模式数据流与仪表盘数据隔离说明。
场景范围：仅算法竞赛（`scene` 固定 `algorithm`）。

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
        双视角 → ARBITER 总仲裁交付最终结果（调用失败 → HUMAN_REVIEW）
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
| 算法·自建 | AtCoder ABC（公开赛题独立产线抓取） | 竞赛题（抓题面+公开 AC 解） | 175 | 官方分值 100→basic, 200-400→medium, 500+→hard | 官方分值 + layer_basis |

- 自建题产线（响应任务书"公开集为主 + 自建补充"）：
  独立抓取产线（抓题面 + AC 解）→ 官方样例 + 人工边界用例（gen_hidden_cases.py，期望由参考解跑出）→ `abc_selfbuilt.jsonl`；
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
    # verify 恒走总仲裁：双视角一致与否都交由 ARBITER 交付最终结果
    # （arbiter ∈ {ARBITER, HUMAN_REVIEW}；V1/V2 仅用于读取历史数据）
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

## 5.4 规则校验定位（executor/static_check.py）

规则校验审的是 **solver 产出的代码实现**（implement 步骤的 artifact）——复杂度
声明一致性、死循环/递归无终止、边界启发式，覆盖 Python 与 C++。它属于
**实现/结果层审核**（对代码这个产物的规则审查），与 verifier 对**推理链文本**
的过程评估是两个正交维度：

- **过程评估（LLM）**：判断推理链是否成立（跳步/误用定理/条件遗漏等）。
- **结果审核（规则/沙盒）**：沙盒判答案对错；规则校验判代码是否满足
  可自动检查的性质（复杂度声明与实现一致、无死循环等）。

因此规则校验**不单独阻断 verdict**：启发式有误报，且不直接判断推理链成立性。
它的输出作为 verifier 的**补充诊断证据**（static_evidence）喂给双视角 LLM 审查，
帮助定位实现层缺陷——对应任务书"规则校验 + 分步 LLM 审查"的多手段组合。

规则黄金样例集与规则配对存放：`tests/test_static_check.py`（每条规则含
"正例应命中 / 负例不误报"），开源后 `pytest tests/test_static_check.py` 即可
验证规则行为，便于后续按需扩展新规则而不影响主判定。

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
- 接入点：① 评测 `run_test_cases(judge=..., checker_code=...)` ② 入库产线以
  `--judge special --checker-file ...` 标注（此时自动找 AC 也用 checker 而非样例比对）。
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
3. **ARBITER 总仲裁**：无论 V1/V2 是否一致，都由仲裁复核双方判定并交付最终
   verdict（findings 合并保留各自 severity）；仲裁调用重试耗尽失败 → 回退高置信
   视角并标 `HUMAN_REVIEW`。
4. `findings` 携带 step_id 供定位与 refine 使用。

### 6.1 缺陷严重度分级（severity）

每条 `ErrorFinding` 带 `severity`：
- **fatal**（实质缺陷）：推理链断裂/关键引理未证且不可重建、误用定理、循环论证、
  逻辑缺陷、推理与代码实质不符、漏处理会致错的条件 → **只有 fatal 驱动
  PROCESS_INCORRECT/SILENT_FAILURE/ANSWER_INCORRECT 判定**。
- **minor**（轻微瑕疵）：表述笔误、自测文字错误、可重建的常规论证省略、
  复杂度叙述不精确但结论仍成立、无害背景误述 → **只记录，不驱动非 CORRECT**。

### 6.2 重建测试（所有缺陷判定的总闸）

怀疑某步有问题时，先问：去掉/修复该句后，剩余推理链 + 题面条件 + 领域常识
能否**重新推出**该结论？
- 能重建 → minor（省略的是平凡/显然/常规推导，不构成过程错误）
- 不能重建 → fatal（结论依赖未给出的关键推理，或该步断言本身错误）
平凡公式/常识（sin30°=1/2、勾股定理、定义直接可推出）不需推导；解题关键
引理（贪心最优性、组合计数、必胜性）仅以"显然"带过 → fatal jump。

### 6.3 判定口径（`Verdict`）

- `CORRECT`：过程成立（无 fatal；可带 minor 记录）且答案正确。
- `PROCESS_INCORRECT`：存在 fatal 过程缺陷，答案可能对也可能错。
- `ANSWER_INCORRECT`：答案与标准答案不符（沙盒/比对为准）。
- `SILENT_FAILURE`：答案正确（沙盒/比对均通过）但存在 fatal 过程根本缺陷。

### 6.4 程序化一致性兜底（pipeline `_reconcile_verdict`）

LLM 判定可能存在自相矛盾，以沙盒客观信号 + severity 做最终裁决：
- 答案正确 + fatal → SILENT_FAILURE（不得 CORRECT/ANSWER_INCORRECT）
- 答案正确 + 无 fatal（全 minor/空）→ CORRECT（剥离 minor 被提升为过程错的误报）
- 答案错误 → 绝不可能是 CORRECT/SILENT_FAILURE（fatal 则 PROCESS_INCORRECT，
  否则 ANSWER_INCORRECT）
- refine 模式无沙盒 → 仅 minor 视同正确（`_strip_minor_only`），避免空转修正。

## 7. 双模式与数据纯净性

| 模式 | CLI | 数据流 | 输出 | 用途 |
|---|---|---|---|---|
| eval | `run-eval` | 一次性：solve→execute→verify，反馈绝不回流 | `data/outputs/eval_{scene}.jsonl` | 全部指标的**唯一**数据来源 |
| refine | `run-refine` | 循环：verify→feedback→revise→re-verify（≤3 轮） | `data/outputs/refine_{scene}.jsonl` | 修正效果对比（不计入 eval 指标） |

- 每轮修正记录 `RefineRound`（修订后答案+反馈+重验证），支持"修正前后对比"。
- 断点续跑：JSONL 追加写，重启跳过已完成 question_id。
- 成本核算：`Hy3Client.call_count` 每实际请求自增（含重试），逐轮/累计可查。

### 7.2 交互式解题（仪表盘演示）的留档与数据隔离

交互演示（现场输入题目 → HY3 求解 → 过程评估）与正式评测**物理分离**，不进入任何统计口径：

| 产物 | 文件 | 说明 |
|---|---|---|
| 交互题池 | `data/questions/interactive.jsonl` | 每次求解分配一个新题号（`IX0001`…）写入；单题回放按题号取题面与用例 |
| 会话快照 | `data/outputs/interact_sessions.jsonl` | 题面/用例/参考解/命中模型/参考解试运行/判定摘要；失败会话同样留档 |
| 判定记录 | `data/outputs/eval_interactive.jsonl` | `source="interactive"`，指标侧 `formal_only` 直接过滤掉 |
| 修正记录 | `data/outputs/refine_interactive.jsonl` | 交互 refine 单独存放，**不写入**数据集注册的正式 refine 文件 |

- 参考解试运行由**服务端**在沙盒里自己跑一遍（不采信前端上传的结果），逐用例留档输入/期望/实际输出；
  C++ 只编译一次后复用到各用例。
- **逐 Step 流式**（`on_step` / `on_reasoning`）：交互演示时求解走
  `Hy3Client.chat_stream` + `rex.stream_json.partial_answer`——按大括号配对流式切出已闭合的
  step 对象，界面边生成边渲染；思考阶段只回传累计字数（Hy3 先推理再出正文）。
  该路径**只在交互演示启用**，正式评测仍走 `chat()` 整段调用 + 完整 JSON 解析，
  判定与成本口径不变（`on_step=None` 即原路径）。
- 交互记录在「单题回放」里按题号回看（列表来源筛选项：`run-eval` / `interactive`）；refine 演示的会话
  额外补一条"终局判定"记录，否则回放列表（按 eval 记录组织）看不到它。

### 7.1 ReAct 自我修正闭环（方法论与收敛判据）

- 首轮与 eval 同路径（solve→verify，initial 可比）；initial==CORRECT 不进修正轮。
- 反馈 = verifier findings 映射修订指令（`findings_to_feedback`）：**仅 fatal 驱动**
  （minor 不空转）、指 `step_id`+`error_type`、同 (step,type) 去重、无定位时兜底整体指令；
  `revise` 接收题目+上一版完整答案+反馈做全量重写，每轮独立 re-verify。
- **收敛判据** = `verdict == CORRECT`（refine 无沙盒，全部 minor 经 `_strip_minor_only`
  置 CORRECT 即停）；**停止条件** = 收敛 / 达 `max_rounds`（默认 3）/ 无反馈可生成。
- 有效性指标 = `refine_comparison`（before/after_correct、improved、converged，报告 §5）。
- 方法论全文与有效性论证：`reports/REACT_METHOD.md`（姊妹篇：题集难度分层
  `DIFFICULTY_SCORING_METHOD.md`、过程评估器 `PROCESS_EVAL_METHOD.md`）。

## 8. SILENT_FAILURE（答案正确但过程根本缺陷）留档

自然评测中 verifier 检出的 `SILENT_FAILURE` 样本（真实评测留档）：
**沙盒答案全对但过程/实现存在根本缺陷**——即任务书"结果正确但过程不成立"的样本。
每条含题目源、检测时间、定位缺陷与步骤、`flaw_answer`（当时模型真实输出）与来源说明，
供逐条核验评估器不会因"答案对"而放行根本缺陷。检出机制与判定口径见 §6；
自然评测中的 SILENT_FAILURE 计数与分布见 `reports/REPORT.md` §1/§7。

## 9. 指标（src/rex/metrics/）

| 指标 | 定义 | 支撑 |
|---|---|---|
| 答案准确率 | 答案正确题目 / 总题 | 算法沙盒全过（无用例时文本比对） |
| 过程正确率 | verdict=CORRECT 题目 / 总题（仅 fatal 驱动非 CORRECT） | 验证 Agent×2+仲裁 |
| 错误定位命中率 | 系统定位 step 与人工标注 ≤1 步 / 答案错误抽检样本 | audit_records.jsonl |
| 误报率（区间） | 答案正确但被判有错样本中人工复核为误报比例。三层复核（`human_severity_match`）：完全相符=系统分级正确；层次不符=fatal/minor 打反（误报侧，主口径计）；完全不符=系统说有错实际过程正确（主/副口径均计）。报告给区间：下界=仅完全不符，上界=含层次不符 | audit_records.jsonl |
| 沉默失败检出 | 自然评测中判定 SILENT_FAILURE 的样本数与占比（识别"答案对但过程根本缺陷"） | eval 结果 |
| 修正提升 | refine 前后过程正确率差 | refine_{scene}.jsonl |
| 置信区间 | Wilson interval（95%） | stats.py |
| 稳定性 | 同档二次抽样指标漂移 | stats.py |

人工抽检三层复核（对系统 fatal/minor 分级是否属实）：
- `match`：系统 fatal/minor 分级正确 → 非误报
- `level_mismatch`：方向对但分级打反（系统把 minor 判 fatal）→ 误报率上界
- `fp`：系统说有错但实际过程正确 → 误报率下界（主/副口径均计）

双口径敏感性：
- 主口径：verdict 由 fatal 驱动（minor 剥离，`_reconcile_verdict` 已落库）
- 副口径：若把 minor 也计入过程错误，过程正确率/误报率各是多少
  （报告并列展示区间两端说明口径敏感性）

### 9.1 minor 统计口径（主口径 / 副口径）

**定义**：`minor` 是 finding 的 severity（`finding.severity == minor`），表示"不破坏推理链成立性的轻微瑕疵"（表述笔误/可重建省略/无害误述）。**verdict 层无 minor 档**；错误分 fatal/minor 两类发生在 finding 层。

**样本三类去向（一切统计的根）**：
| 类 | verdict | findings | 主口径(默认) | 副口径(minor_as_error) |
|---|---|---|---|---|
| A 干净 | CORRECT | 空 | 过程正确 | 过程正确 |
| B **仅 minor 记录** | CORRECT | 全 minor | 过程正确 | **过程错误** |
| C fatal 驱动 | SILENT/PROCESS_INCORRECT/ANSWER_INCORRECT | 有 fatal（可附 minor） | 过程错误 | 过程错误 |

**流转链（代码逐点）**：
1. V1/V2/ARBITER 判定产出 findings（带 severity）——**总仲裁交付最终 verdict**；
2. eval reconcile（`_reconcile_verdict`，有沙盒信号）：答案对+无 fatal → CORRECT（**minor 被"剥离"，findings 保留** → B 类）；答案对+有 fatal → SILENT_FAILURE（C 类）；答案错 → PROCESS_INCORRECT/ANSWER_INCORRECT；
3. refine（`_strip_minor_only`，无沙盒）：仅 minor → CORRECT 即停（不空转）；
4. metrics：`_is_process_correct`——主口径看 verdict==CORRECT；副口径要求 CORRECT 且 findings 为空（B 类变错）；`compute_metrics(minor_as_error=...)` 统一入口；
5. 抽检（`audit_metrics`）：误报率分母=答案对且被判过程有错。主口径判据 verdict∈{PI,SF}；副口径追加 verdict==CORRECT 且 findings 非空（B 类入分母）。三层复核 `human_severity_match`：`level_mismatch`（系统把 minor 判 fatal）主口径误报、副口径不计；`fp` 两口径均误报；
6. 报告呈现（`make_report.py` §1 总览）：过程正确率主/副并列 + **"仅 minor 记录样本 N（主口径对/副口径错）"**；§6 误报率区间。

**当前基线（359，temp0 前）**：CORRECT 300 = 282 干净 + **18 仅 minor 记录**（A1013/A1024/A1104/C2106 等）；SILENT_FAILURE 18（17 无 minor + 1 附 minor）；PROCESS_INCORRECT 33（25 无 + 8 附 minor）。

**关于 "minor 与 SILENT_FAILURE（答案对但过程错）的关系"（防误读）**：
- SILENT_FAILURE 由 **fatal** 驱动，不是 minor；
- 无 fatal 的 minor-only 样本 reconcile 后为 CORRECT（B 类，主口径正确），**不会进入 SF**；
- minor 出现在 SF 的常见形态是**人工核验纠正**：系统把实质 minor 误判为 fatal → 样本被误放入 SF/PI → 抽检判 `level_mismatch`（C2118/C2140）。因此 SF 中与 minor 相关的统计 = `level_mismatch` 计数，不是 minor finding 计数。

**temperature=0 全量重做 checklist（不覆盖当前记录）**：
1. 生成侧：`REX_TEMPERATURE=0` 跑 `python -m src.cli run-eval --questions abc_selfbuilt.jsonl --sample full`（默认输出 `eval_abc_selfbuilt_t0.jsonl`；CF 同理 `eval_cf_selfbuilt_t0.jsonl`）——写独立文件，temperature=0.9 时代的 `eval_*_all.jsonl` 原样归档保留；
2. 读取侧：`export REX_EVAL_SUFFIX=_t0` 后，`make_report.py`/审计/仪表盘统一读 t0 记录（`datasource.evals_path` 按后缀解析；不设该环境变量即读默认注册文件）；
3. 每样本自动产出 answer_correct/verdict/findings(severity)/arbiter(=ARBITER 总仲裁)；
4. 统计统一走 `make_report.py`（§1 主/副 + minor-only 行、§6 抽检区间）——主/副口径按 §9.1 路线自动一致；
5. 抽检模板基于 t0 记录重新生成（`scripts/audit_sample.py`），标注仍按 `audit_rules.md` v4，回填后同步 `data/audit/` 副本；
6. 新旧两套记录并存于 `data/outputs/`，报告/表格注明数据版本（默认注册文件 = temp0 前基线，`REX_EVAL_SUFFIX=_t0` = 重跑结果）。

## 10. 运行方式

```bash
# 环境（优先级：优先 tensor_env，其次 anaconda）
#   D:\.conda\envs\tensor_env\python.exe  (Python 3.9, 推荐, run.ps1 默认)
#   D:\ProgramData\anaconda3\python.exe   (Python 3.13, 备选)
#   .\run.ps1 ...  统一入口；或 $env:REX_PYTHON=... 覆盖解释器
# .env 提供 HY3_API_KEY / HY3_BASE_URL / HY3_MODEL

# 评估模式（数据纯净）
python -m src.cli run-eval --scene algorithm --sample 100      # 放大（样例验证）

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
  - `abc_selfbuilt.jsonl`（AtCoder ABC 175 题）/ `cf_selfbuilt.jsonl`（Codeforces 184 题）：含 AC 参考解、公开+隐藏用例、SPJ checker、分层依据（layer_basis）
  - TACO 公开镜像（`algorithm.jsonl`，约 82MB）不入库，可由公开 HF 数据源重建（本地 dataset-full 分支保留完整数据）
- SILENT_FAILURE 留档：真实评测检出的「答案对但过程根本缺陷」样本，作为 `verification.findings` 随评测结果一并交付
- 评估结果 data/outputs/（eval/refine 严格分离，可断点续跑），随仓库交付的文件：
  - `eval_abc_selfbuilt_t0.jsonl`（175 题）/ `eval_cf_selfbuilt_t0.jsonl`（184 题）：temperature=0 正式评测全量记录（含模型过程与代码、判定、findings、静态校验、沙盒通过率）
  - `refine_wrong_t0.jsonl`（36 条）：答案错样本的 ReAct 修正逐轮记录
  - `contamination_probe.jsonl`（30 题）+ `contamination_probe_pilot.jsonl`（6 题）：记忆暴露行为探测
  - `diff_scores.jsonl`（359 条）：统一难度分与三专家盲打明细
  - `eval_interactive.jsonl` / `interact_sessions.jsonl` / `interactive.jsonl`：交互演示留档（判定记录 / 会话快照 / 交互题池），属演示产物，不进任何统计
  - 不入库：`_archived/`（历史分片）、运行日志（`*.log`/`*.err`）、`audit_records*.jsonl` 与 `audit_rules.md`（以 `data/audit/` 为权威版）
- 分析报告 reports/（分层退化、错误分布、case 归因、修正前后对比、能力画像）
- 方法论文档 reports/：`DIFFICULTY_SCORING_METHOD.md`（题集统一难度分层）、
  `PROCESS_EVAL_METHOD.md`（过程评估器判定）、`REACT_METHOD.md`（ReAct 自我修正闭环）
- 人工抽检记录 data/audit/audit_records.jsonl（48 条，含用户终审）+ 抽检规则 data/audit/audit_rules.md

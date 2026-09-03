# 过程评估 · 代码逐行对照解读

> 目标：把"系统在做什么"和"代码在哪、为什么这么写"对齐，让你不看一遍代码也能看懂，看代码时又能快速定位。
> 阅读方式：每节先讲**功能**，再给**代码位置 + 逐行要点**。

---

## 0. 一张图看懂全流程

```
src/cli.py  (命令行入口)
   │  run-eval / run-refine
   ▼
src/rex/pipeline.py  (Pipeline：编排两种模式)
   │
   ├─ eval 模式（数据纯净，一次性）：solve → execute → verify
   │    │                                        │
   │    ▼                                        ▼
   │  solver/agent.py                        verifier/agent.py
   │  (解题/修订)  ──────────────►           (双视角核对 + 仲裁)
   │                                            │
   │                    executor/tests.py  ◄────┤ ① 沙盒执行答案
   │                    (测试用例/文本比对)      │
   │                                            ▼
   │                                  models.py  (Verdict 判定结果)
   │
   └─ refine 模式（ReAct 闭环）：solve → verify → [feedback → revise → re-verify] ≤N 轮
          │
          ▼
      refine/agent.py  (Refiner 驱动循环)
```

**两个最关键的设计点**（贯穿全程，先记住）：

1. **`models.py` 是唯一的"合同"** —— 每个阶段之间交换的 JSON 都严格符合这里定义的 Pydantic 模型，改这里会波及全流程。
2. **eval 与 refine 严格分离** —— eval 的结果永远不把 verifier 反馈送回 solver；refine 是独立模式，独立文件、独立指标。保证"评估指标不被自我修正污染"。

---

## 1. 数据结构层：`src/rex/models.py`

所有阶段交换的 JSON 都在这定义。**这是整个系统的地基**。

### 核心类与作用

| 类 | 作用 | 出现在哪 |
|---|---|---|
| `Step` | 解题的一步：id、类型、内容、结论、依赖 | solver 输出、verifier 审 |
| `Answer` | 完整解题过程：steps 列表 + 最终答案 + 代码 | solver → verifier → executor |
| `ErrorType` | 错误类型枚举（6 基线 + 3 扩展 + other） | verifier findings、refine 反馈、报告 |
| `Verdict` | 四类判定 | verifier 输出、指标 |
| `VerificationResult` | 判定结果（verdict + findings + confidence + arbiter） | 单题评估的"过程评价" |
| `EvalRecord` | **单题评估的完整记录** | eval 输出 JSONL |
| `RefineRecord` | 单题修正记录（含每轮轨迹） | refine 输出 JSONL |
| `GoldenSample` | 沉默失败陷阱样本（答案对但过程错） | golden 检出测试 |

### 关键代码要点

**① 四类判定 `Verdict`（过程评估的核心输出）**
```62:67:src/rex/models.py
class Verdict(str, Enum):
    CORRECT = "CORRECT"                     # 过程与答案均正确
    PROCESS_INCORRECT = "PROCESS_INCORRECT" # 过程有问题（答案可能对也可能错）
    ANSWER_INCORRECT = "ANSWER_INCORRECT"   # 最终答案错误
    SILENT_FAILURE = "SILENT_FAILURE"       # 答案正确但过程不成立
```
> 这四类就是"过程评估"的落点。注意 `SILENT_FAILURE` —— 整个系统的核心价值就是抓住这类"答案对、过程错"的沉默失败。

**② `Step` 的 `deps` 字段（自含性检查 + 全局回溯的依据）**
```18:29:src/rex/models.py
class Step(BaseModel):
    id: int
    kind: Literal[...]
    content: str       # 本步文本（推导/代码/说明）
    conclusion: str    # 本步结论（供自含性检查）
    deps: list[int] = Field(default_factory=list)  # 依赖的前置步骤 id（供全局回溯）
```
> 每一步都自带"结论"和"依赖了哪些前置步骤"——这是后面双视角验证器（一个查局部、一个查全局）能工作的数据结构基础。

**③ `VerificationResult`（过程评价的载体）**
```69:74:src/rex/models.py
class VerificationResult(BaseModel):
    verdict: Verdict
    findings: list[ErrorFinding] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    arbiter: Literal["V1", "V2", "ARBITER", "HUMAN_REVIEW"] = "ARBITER"
    timestamp: float | None = None  # epoch 秒，供耗时分析
```
> `arbiter` 记录这次判定是哪个审查员/仲裁者给的 —— 便于审计与归因。

---

## 2. 入口层：`src/cli.py`

命令式入口，把用户指令映射到 `Pipeline` 的两种模式。

### 关键命令
```4:15:src/cli.py
    # 评估模式（数据纯净，一次性）
    python -m src.cli run-eval --scene algorithm --sample 5
    python -m src.cli run-eval --scene algorithm --sample 10 --resume

    # 修正模式（ReAct 闭环，限 3 轮）
    python -m src.cli run-refine --scene algorithm --sample 5
```

### 关键代码要点
- `run_eval` 命令（`54-77` 行）：读题集 → 抽样 → 建 `Pipeline` → `pipe.run_eval(...)` → 写 `data/outputs/eval_*.jsonl`。
- `run_refine` 命令（`80-105` 行）：同上，但走 `pipe.run_refine(...)`，写 `refine_*.jsonl`，且可设 `--max-rounds` 限轮数。
- 两者都**默认开启 `--resume`**（断点续跑）。

---

## 3. 编排层：`src/rex/pipeline.py` —— 核心中的核心

`Pipeline` 把 solver / verifier / executor 串起来，提供两种模式的统一入口。

### 构造函数：组装三件套
```54:67:src/rex/pipeline.py
class Pipeline:
    def __init__(self, config: Config, client: Hy3Client | None = None) -> None:
        self.config = config
        self.client = client or Hy3Client(...)   # ① 统一一个 HTTP 客户端
        self.solver = SolverAgent(self.client)    # ② 解题器
        self.verifier = VerifierAgent(self.client) # ③ 验证器
        self.refiner = Refiner(self.solver, self.verifier) # ④ 修正器（refine 用）
```
> 三件套共享同一个 `client`，这样 `client.call_count` 就是全流程的真实调用数（成本核算唯一来源）。

### eval 模式：`run_eval`
```86:105:src/rex/pipeline.py
        with out.open("a", encoding="utf-8") as f:
            for q in questions:
                if q.id in done:      # 已完成的题号直接跳过（断点续跑）
                    continue
                try:
                    rec = self._eval_one(q)
                except Exception as e:   # 单题失败 → 占位记录 + error，不中断批
                    ...
                f.write(rec.model_dump_json() + "\n")  # 每完成一题立即落盘
                f.flush()
```
> 这就是"暂停不丢数据"的机制：追加式写入 + flush，配合 `resume` 跳过已完成题号。

### eval 单题核心：`_eval_one`（过程评估主链路）
```107:126:src/rex/pipeline.py
    def _eval_one(self, q: QuestionItem) -> EvalRecord:
        t0 = time.time()
        answer = self.solver.solve(q)                      # ① 模型解题
        answer_correct, pass_rate, _ = self._execute(q, answer)  # ② 客观校验
        verification = self.verifier.verify(q, answer)     # ③ 过程评价
        rec = EvalRecord(..., answer_correct=answer_correct, ..., verification=verification, ...)
```
> **一行 `verification = self.verifier.verify(...)` 就是"过程评估"本身** —— 客观的答案对不对（`_execute`）和主观的过程好不好（`verify`）是分开记录的。

### 客观校验：`_execute`（答案对不对）
```169:187:src/rex/pipeline.py
    def _execute(self, q, answer) -> tuple[bool|None, float|None, str|None]:
        # 算法场景：有代码+用例走沙盒；无用例时比对 standard_answer 文本
        # (归一化用 normalize_answer_text)
        if answer.code and q.test_cases:   # 算法：沙盒跑测试用例
            res = run_test_cases(answer.code, q.test_cases)
            return (res.pass_rate >= 1.0), res.pass_rate, res.error
```
> `answer_correct`（客观）和 `verification.verdict`（主观）是两个维度，报告里分开统计 —— 这正是"沉默失败"能被发现的入口。

---

## 4. 解题层：`src/rex/solver/agent.py`

Solver 负责两件事：`solve`（独立解题）和 `revise`（根据反馈修订）。两者都输出结构化 `Answer`。

### 关键代码要点
- **`solve`（36-40 行）**：eval 路径，题目 → 首次答案，无反馈。
- **`revise`（42-56 行）**：refine 路径，上一版答案 + 验证反馈 → 修订版。对算法长答案做了 8000 字符截断控制 token 成本。
- **JSON 容错（67-83 行 `_ask`）**：模型可能输出带 markdown 围栏 / 前导废话 / 非法 JSON，解析失败会把错误**回喂给模型**重试（最多 2 次）。
- **场景合法性校验（94-102 行 `_validate_kinds`）**：step 的 `kind` 必须符合算法场景白名单（understand/approach/complexity/implement/selftest）。

---

## 5. 验证层：`src/rex/verifier/` —— 过程评估的核心引擎

这是"过程评估"真正的实现。分两个文件：`agent.py`（逻辑）和 `prompts.py`（提示词）。

### 5.1 双视角 + 仲裁：`agent.py`

**`verify` 主逻辑（39-64 行）** —— 两个独立审查员 + 分歧时仲裁：
```39:64:src/rex/verifier/agent.py
    def verify(self, question, answer) -> VerificationResult:
        v1 = self._verify_view("A", question, answer)   # 视角A：自含性优先
        v2 = self._verify_view("B", question, answer)   # 视角B：全局回溯优先

        if v1.verdict == v2.verdict:      # 两视角一致 → 合并 findings
            merged = self._merge(v1, v2)
            merged.arbiter = "V1" if v1.confidence >= v2.confidence else "V2"
            ...
        # 分歧 → 第三次调用仲裁
        verdict = self._arbitrate(question, answer, v1, v2)
```
> 为什么是双视角？单一视角容易漏检；一个"自含性"（局部每步对不对）、一个"全局回溯"（整体链条是否成立），互补。仍不一致就请"首席仲裁员"裁决，规则是**证据充分的错误优先于答案正确**（防沉默失败放行）。

**`_verify_view`（67-71 行）**：构造提示词 → 调模型 → 解析成 `VerificationResult`。A/B 视角只是 system prompt 不同。

**`_merge`（109-123 行）**：两视角一致时合并 findings（去重）、取 max confidence。

### 5.2 提示词与判定标准：`prompts.py`

**核心判定标准 `_VERDICT_RULES`（17-49 行）** —— 直接告诉模型怎么判，含"沉默失败"专项提醒：
```21:24:src/rex/verifier/prompts.py
- SILENT_FAILURE     : 最终答案正确，但过程存在根本性错误（如结论凭运气成立、
                        关键步骤错误却得到正确数字）——必须识别，不能放行
注意：最终答案正确 ≠ 过程正确。
```
> 这就是系统能检出"答案对但过程错"的根本原因 —— 在提示词层面就强制模型不得因答案正确而放行。

**双视角设定 `verifier_system`（52-68 行）**：
```52:68:src/rex/verifier/prompts.py
def verifier_system(view: str) -> str:
    if view == "A":
        # 自含性优先：逐条检查每步 conclusion 能否由 content+deps 推出
        # 重点抓：计算错误、概念错误、条件遗漏、格式不符
    else:
        # 全局回溯优先：从最终答案沿依赖链反向回溯
        # 重点抓：跳步推导、题意误读、逻辑缺陷、边界条件
        # 特别注意识别「答案正确但过程不成立」的沉默失败
```

**仲裁规则 `ARBITER_SYSTEM`（86-93 行）**：
```86:92:src/rex/verifier/prompts.py
    1. 任何一方发现可验证的错误（引用具体步骤内容/数字），该错误即为事实，采纳之
    2. 证据充分的错误优先于「答案正确」——SILENT_FAILURE 与 PROCESS_INCORRECT 优先于 CORRECT
```
> 仲裁的倾向性设计：宁可判"过程有错"也不放行沉默失败。

### 5.3 错误分类体系：`errors.py`

定义 10 类错误（`models.py` 的 `ErrorType`），三处复用：
1. verifier 提示词要模型找哪几类错误；
2. refine 反馈要映射成可操作的修订指令；
3. 报告要按错误类型画能力画像。

**`root_cause`（66-70 行）**：从多个 findings 里挑最"根本"的那个错误（按定义顺序取最小序号）—— 用于归因分析。

---

## 6. 执行层：`src/rex/executor/tests.py`

对算法场景做沙盒执行 + 测试用例比对。

### 关键代码要点
- **`run_test_cases`（23-68 行）**：逐用例隔离执行（`run_code` 在 `sandbox.py`），比对 stdout。
- **隐藏用例不泄露**（55-58 行）：`tc.hidden` 为真时只计数不记录内容。
- **输出归一化**（50-51 行）：去尾部空白、容忍单个空行差异。
- **编译/运行错误捕获**（43-48 行）：语法错误记入 `error`，其余继续跑。

---

## 7. 指标层：`src/rex/metrics/compute.py`

基于 eval 数据算出核心指标。**注意：只用 eval 数据（数据纯净性）。**

### 关键函数与要点
- **`compute_metrics`（67-95 行）**：
  - `answer_accuracy`（答案准确率）：`_is_answer_correct` 判定（沙盒全过 或 文本比对通过）。
  - `process_correctness`（过程正确率）：`verification.verdict == CORRECT`。
  - `verdict_dist`：四类判定占比（**含 SILENT_FAILURE 检出率**）。
  - `error_type_dist`：错误类型分布（能力画像）。
  - `per_tier`：按难度三档分层（分层退化分析）。
- **`audit_metrics`（109-145 行）**：有人工抽检标注时，算"错误定位命中率"和"误报率"。
- **`refine_comparison`（160-180 行）**：修正前后对比（初始 vs 收敛轮）。

### 最关键的一行逻辑
```73:73:src/rex/metrics/compute.py
    process_correct = sum(r.verification.verdict == Verdict.CORRECT for r in records)
```
> 这就是"过程正确率"的定义 —— 只要 verdict 不是 CORRECT 就视为过程不过关（含 ANSWER_INCORRECT、SILENT_FAILURE、PROCESS_INCORRECT）。

---

## 8. 自我修正闭环：`src/rex/refine/agent.py`

refine 模式驱动 ReAct 闭环。`Refiner.refine` 是核心。

### 关键代码要点
```43:71:src/rex/refine/agent.py
    def refine(self, question) -> RefineRecord:
        answer = self._solver.solve(question)          # 首轮：与 eval 同路径
        initial = self._verifier.verify(question, answer)
        if initial.verdict != Verdict.CORRECT:         # 初始不对才进闭环
            for round_no in range(1, self._max_rounds + 1):
                feedbacks = findings_to_feedback(...)  # findings → 修订指令
                revised = self._solver.revise(question, current_answer, feedbacks)  # 修订
                current_v = self._verifier.verify(question, revised)               # 复验
                if current_v.verdict == Verdict.CORRECT:
                    break                              # 收敛即停
        converged = current_v.verdict == Verdict.CORRECT
```
> **闭环逻辑**：验证发现错 → 把 findings 翻译成反馈 → 让 solver 修订 → 再验证 → 直到 CORRECT 或轮数耗尽。每轮完整记录（`RefineRound`），供报告做修正前后对比。

---

## 9. 按"你想看什么"快速定位

| 你想找 | 去这里 |
|---|---|
| 过程评估"整体怎么串起来的" | `pipeline.py` 的 `_eval_one`（107-126 行） |
| 过程评估"怎么判定对错" | `verifier/prompts.py` 的 `_VERDICT_RULES`（17-49 行） |
| 双视角验证逻辑 | `verifier/agent.py` 的 `verify`（39-64 行） |
| 错误类型清单 | `verifier/errors.py` + `models.py` 的 `ErrorType` |
| 指标怎么算的 | `metrics/compute.py` 的 `compute_metrics` |
| 自我修正闭环 | `refine/agent.py` 的 `refine`（43-71 行） |
| 所有数据"合同" | `models.py`（Verdict/Answer/Step/EvalRecord） |
| 暂停续跑机制 | `pipeline.py` 的 `run_eval`（79-105 行） |

---

## 10. 一段话总结

**过程评估** = 让大模型解出题目（solver）→ **用双视角审查员 + 仲裁判定过程对不对（verifier，重点抓"答案对但过程错"的沉默失败）** → 同时用沙盒/比对客观验证答案对不对（executor）→ 把两种"对不对"记进 `EvalRecord`（models.py）→ 最后在 `compute_metrics` 里分别统计"答案准确率"和"过程正确率"（metrics）。

**自我修正**（refine）则是把 verifier 找到的错翻译成反馈，让 solver 反复修订直到过程被判定正确，独立于 eval 单独成册、单独出指标。

所有阶段只通过 `models.py` 的 JSON 合同交换数据，全程 `jsonl` 持久化、可断点续跑，模型输出永远被当作"数据"而非"指令"。


1：过程正确性判定：判断推理链条是否成立，是否存在跳步、循环论证、误用定理、条件遗漏、幻觉等问题，这个判断具体是怎么实现的，以及为什么要这样实现。
2： 错误步骤定位：当解答错误时，定位错误开始出现的步骤
 错误类型归类：建立错误分类体系，例如题意误读、概念理解错误、计算错误、条件
遗漏、跳步推导、格式不符等
 结果正确但过程不成立的样本识别：例如猜中选项、数值巧合、误用定理却得出正确
结果、恰好通过测试用例但实现逻辑存在缺陷等情况
另外过程评估还应该包括什么内容比较合适

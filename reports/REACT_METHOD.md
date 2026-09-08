# ReAct 自我修正方法论（验证驱动修订闭环）

> 面向项目书「过程评估设计 · 分步 LLM 审查/多 Agent 交叉复核」延伸要求与
> 「评估器定位结果如何被利用」的方法论论证：过程评估器定位出的错误步骤与
> 类型，如何转化为求解智能体的**可操作修订指令**，形成 ReAct 闭环，以及
> 如何用指标证明闭环有效、何时收敛、何时停止。
> 数据日期：2026-09-08 ｜ 判定版本：severity v1（仅 fatal 驱动修正）
> 执行模块：`src/rex/refine/{agent,prompts}.py` ｜ 指标：`src/rex/metrics/compute.py::refine_comparison`
> 姊妹篇：`reports/DIFFICULTY_SCORING_METHOD.md`（题集难度分层）、
> `reports/PROCESS_EVAL_METHOD.md`（过程评估器判定）；本文对应「评估器的输出
> 如何回到求解端形成自我修正」。

---

## 1. 问题：为什么需要自我修正闭环

任务书要求对"可验证场景"的解题过程做评估，但这只完成了**检测**：把过程
判为有错、定位到步骤、归好类型。检测结果若不回流，就只是一张"体检报告"。
ReAct 思想（Reasoning + Acting 交替）把"检测"升级为"治疗"：

- **Reason**：评估器给出缺陷判定（verdict + findings，每条带 `step_id`/
  `error_type`/`detail`/`evidence`）；
- **Act**：求解智能体据修订指令重写解题过程；
- 再 Reason（re-verify）→ 再 Act，直到收敛或达轮数上限。

因此闭环的价值有二：**① 让被评估对象（求解过程）能利用评估结果自我改进**；
**② 反证评估器的定位质量**——若定位与反馈不准确，修正不会收敛，这本身
就是评估器有效性的一个观测面（定位错 → 修正率低；误报 minor 当 fatal →
空转修正）。

## 2. 设计：验证驱动修订的循环

### 2.1 循环结构（`Refiner.refine`）

```
首轮：solve（与 eval 模式同路径）→ verify → initial
      （initial == CORRECT → 无 rounds，直接返回）
修正轮 for round_no in 1..max_rounds（默认 3）：
    findings_to_feedback(当前 verdict) → 修订指令
    无反馈可生成 → break
    solve.revise(题目, 上一版答案, 反馈) → 新版
    verify(新版) → current_v（_strip_minor_only 后）
    记 RefineRound(round_no, revised_answer, feedbacks, verification, cost_calls)
    current_v == CORRECT → break（收敛）
```

关键点：

- **首轮与 eval 同路径**：initial 用独立求解 + 独立验证得到，保证"修正前"
  状态可复现、与 eval 基线可比，不是事后改写的历史。
- **每轮全量重写**：`revise` 接收的是"题目 + 上一版完整答案 + 本轮反馈"，
  输出完整新过程（不是补丁），避免局部修补引入不一致。
- **逐轮留痕**：每轮修订答案/反馈/重验证/成本均入 `RefineRound`，支持
  逐轮轨迹回放与"修正前后对比"。

### 2.2 反馈的可操作性（`findings_to_feedback`）

评估器 finding 不是给人看的描述，而是**指令源**。转换规则：

1. 只对 `severity == fatal` 生成指令——minor 不破坏推理链成立性，驱动修正
   只会空转（与 eval 侧 reconcile 语义一致：无 fatal 不判过程错）。
2. 指令 = `第 N 步存在{error_type}类问题（{describe}）：{detail}。请修正该步
   及相关联步骤，并重新输出完整解题过程。`——**指步 + 点型 + 给因 + 明动作**。
3. 同 `(step_id, error_type)` 只保留首条：避免同一步被同质指令轰炸。
4. 兜底：verdict 非 CORRECT 却无具体 finding（如纯 ANSWER_INCORRECT 无定位）
   → 生成整体指令（"重新完整推导并核对最终答案，确保每一步可验证"）。

### 2.3 无沙盒下的语义对齐（`_strip_minor_only`）

refine 模式**不做沙盒执行**（不产生 `answer_correct` 客观信号），只能依赖
verifier 判定。为避免"仅 minor 瑕疵也进入修正循环"的空转，refine 侧沿用
eval 侧的 severity 裁决：全部 findings 为 minor → 强制 `CORRECT` 即停
（`_strip_minor_only`）。

## 3. 有效性论证

### 3.1 有效的前提：定位准确 + 反馈可行动

闭环修得对，依赖两件事，均有独立机制保证/验证：

1. **评估器定位可信**：severity + 重建测试保证"发现的确实是实质缺陷且指对
   步骤"（见 `PROCESS_EVAL_METHOD.md` §3.2/§4，难题区间小样本定位 100%、
   误报 0/4）。定位若偏，指令就偏，修正不收敛——所以**收敛率本身是评估器
   定位质量的一个下游观测**。
2. **反馈与求解器接口对齐**：指令携带 verifier 的 `step_id`/`error_type`
   体系，而 solver 的 `revise` prompt 同用这套错误分类名，指令可被直接消费。

### 3.2 为什么不容易越改越差

- 指令**指步不改全局**：只要求修指定步骤及其关联步骤，其余过程不动，约束
  了搜索半径；
- **保留上一版完整答案**为基底做修订，不是从零重解，避免随机漂移；
- 每轮都有独立 re-verify 把关，**不会把改坏的结果当作成功**（判定仍是
  客观流程，不是模型自我感觉良好）；
- 轮数上限兜底：即使反馈错误/难收敛，也不无限消耗。

### 3.3 指标体现（`refine_comparison`，报告 §5）

闭环是否有效，用四组读数回答：

| 指标 | 定义 | 回答的问题 |
|---|---|---|
| `before_correct` | 首轮 verdict=CORRECT 比例 | 基线过程正确率 |
| `after_correct` | 最终（限轮内）verdict=CORRECT 比例 | 修正后过程正确率 |
| `improved` | 首轮错→最终对的样本比例 | **闭环真的修好了多少** |
| `converged` | 限轮内达成 CORRECT 比例 | 收敛能力（含首轮即对） |
| `cost_calls`（记录字段） | 每样本累计 Hy3 调用次数（含首轮与逐轮） | 修正代价 |

组合判读：

- `improved` 显著 > 0 → 修正有效（评估器定位被下游利用成功）；
- `after_correct` 远高于 `before_correct` → 闭环整体增益；
- 若 `improved`≈0 但 `after_correct` 高 → 基线本就高（无修正空间）；
- 若普遍不收敛 → 查评估器定位质量或反馈可执行性（下游反哺上游的告警信号）。

## 4. 收敛判据与停止

**收敛判据（形式化）**：`verdict == CORRECT` 且 `findings` 无 fatal
（refine 侧经 `_strip_minor_only` 归一化）。含义是"verifier 不再认为过程
存在实质缺陷"。

**停止条件（三选一先到）**：

1. 收敛（`current_v == CORRECT`）——正常终止；
2. 达到 `max_rounds`（默认 3）——限轮截断，防无限迭代；
3. 无反馈可生成（理论上仅 CORRECT 出现，防御性 break）。

**收敛有效性的观测方式**（不只是"停了没"）：

- 看 `RefineRound` 逐轮 verdict 轨迹：`PI/SF → CORRECT` 是真实收敛；
  `PI → ANSWER_INCORRECT → CORRECT` 属"改对判定但可能改法曲折"，抽查
  修订 diff 判断是否偏离题意；
- 结合成本：收敛轮数均值 + `cost_calls` 给出"修好一道题的代价"；
- 注意：refine 无沙盒，**收敛到 CORRECT ≠ 沙盒证明答案对**——它是"评估器
  认为过程成立"。需在 eval 侧（有沙盒）对 final 复核才能闭环确认（见 §6）。

## 5. 数据纯净性与成本

- **eval / refine 严格分离**：eval 是单次 solve→execute→verify，反馈绝不
  回流求解端（数据纯净，是全部评估指标的**唯一**来源）；refine 独立文件
  `refine_{scene}.jsonl`，逐轮记录，只用于修正效果对比，**不混入评估指标**。
- **成本可核算**：`Hy3Client.call_count` 按实际请求自增（含重试）；
  `RefineRecord.cost_calls` = 单样本累计；`RefineRound.cost_calls` = 该轮
  新增。solver/verifier 共享同一 client，计数以 client 单值为准（不可相加
  避免双倍）。
- **断点续跑**：JSONL 追加写，重启跳过已完成 question_id。

## 6. 边界与诚实声明

- **无沙盒信号的局限**：refine 收敛判据依赖 verifier 文本判定，不含执行
  事实。若 verifier 对该题漏检（把真 fatal 当 minor）或误报（把可重建省略
  当 fatal），闭环分别表现为"假收敛"与"空转修正"。缓解：
  ① severity 判定质量由 golden 库 + 人工抽检监控（`PROCESS_EVAL_METHOD.md`）；
  ② refine 输出的 final 可作为一轮新的 eval 输入复核（沙盒对答案下最终结论）。
- **修正有效性受求解器执行限制**：指令可执行 ≠ 模型一定按指令改对；模型
  采样有随机性，故"修正前后对比"应基于样本级统计而非单例结论。
- **本文档定稿时 refine 数据未落库**（报告 §5 显示"暂无 refine 数据"）。
  上文指标公式与代码一致，跑通 `run-refine` 后 `make_report.py` 会自动输出
  该节读数，无需改码。

---

## 附：执行与复现

```bash
# 修正模式（ReAct 闭环，≤max_rounds 轮）
python -m src.cli run-refine --questions abc_selfbuilt.jsonl --sample full \
    --max-rounds 3 --resume

# 报告中 §5「修正闭环（ReAct 前后对比）」自动读取 refine_{scene}.jsonl 输出：
#   before_correct / after_correct / converged / improved / 成功修正样本清单
python scripts/make_report.py --out reports/REPORT.md
```

**方法论要点速览**：过程评估定位出 step_id+error_type+evidence 后，不经人
手直接映射为修订指令回流求解端（Reason↔Act 交替）→ 仅 fatal 驱动、同步
去重、兜底整体指令 → 每轮全量重写 + 独立 re-verify → CORRECT 收敛 /
3 轮截断 → `refine_comparison` 以 before/after/improved/converged 四指标
证明"检测被下游利用"的有效性，refine 数据与 eval 指标严格隔离，成本以
call_count 透明可查。

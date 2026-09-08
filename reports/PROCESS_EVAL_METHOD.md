# 过程评估器的搭建思路与判定方法

> 面向项目书「过程评估设计」与「过程评估器有效性验证」章节的方法论论证。
> 数据日期：2026-09-07 ｜ 判定重构版本：severity 语义 v1（P1–P4）
> 模型：Hy3（混元大模型）｜ 执行脚本：`src/cli.py re-verify` / `src/rex/verifier/` / `src/rex/executor/static_check.py`
> 姊妹篇：`reports/DIFFICULTY_SCORING_METHOD.md`（题集统一难度分层）；本文对应「评估器本身怎么搭、为什么这么搭、怎么验证它可靠」。

---

## 1. 问题：评估器要回答什么，为什么难

对一个"可验证场景"（算法竞赛题）的解题过程做评估，需要**不只判断最终答案对错**，
还要判断**推理过程是否成立**、定位出错步骤、归纳错误类型，并识别一类隐蔽样本：
**最终答案正确但推理过程无法支撑该结论**（任务书：猜中选项、数值巧合、误用定理
却得对、恰好通过用例但实现逻辑有缺陷）。

难点在于"过程是否成立"是一个**开放性判断**：
- 解题过程的自然形态是"省略平凡推导、直接引用公式定理"的——要求逐步展开一切
  会误伤大量正确答案；
- 但另一方面，答案全对 + 用例全过的过程**也可能有致命缺陷**（复杂度超限、数组
  越界、分支遗漏恰好未被用例覆盖）——这类缺陷必须被识别，否则评估器形同虚设。

这两条要求互相拉扯：**判严了误报多，判松了漏检多**。评估器搭建的核心问题就是：
在"平凡省略可豁免"与"实质缺陷必检出"之间，建立一条**可操作、可复现、可验证**的
分界线。

---

## 2. 为什么不直接复用旧判定（本次重构的动机）

旧版评估器（2026-09-03 定稿）采用"双视角 LLM 审查 + 仲裁"，已实现过程正确性
判定、错误定位、错误归类、SILENT_FAILURE 检出。但在有效性验证中发现三个结构性问题：

### 2.1 判定粒度缺失：任何 finding 都驱动"过程有错"

旧版 `Verdict` 语义：发现**任何** finding（哪怕只是"自测文字笔误""表述不精确"）
即判 `PROCESS_INCORRECT` / `SILENT_FAILURE`。这导致两个后果：

- **误报率被结构性推高**：答案正确、推理成立的样本，只因存在一句无害表述瑕疵
  就被判过程有错，进入"误报率分母"，人工核验后大量确认为误报。
- **微小错误没有归类位置**：表述瑕疵、可重建的论证省略、无害背景误述，在旧
  判定体系里与"误用定理""逻辑缺陷"被同等对待——缺少一个"只记录、不判错"
  的档位。

### 2.2 判定一致性依赖 LLM 自觉，无程序化兜底

LLM 可能自相矛盾：报告了实质缺陷（fatal）却仍判 `CORRECT`；或答案客观正确、
仅 minor 瑕疵却被判过程错。旧版没有用"沙盒答案正确性 + findings 严重度"做
**程序化的最终裁决**，verdict 语义完全交给模型采样。

### 2.3 规则校验（任务书第 4 类手段）存在语言盲区

复杂度声明一致性、死循环/递归无终止检测基于 Python `ast` 解析；而 CF/ABC 主场景
代码是 **C++**（实测 CF 128/184、ABC 80/175），这些样本的复杂度比对/死循环/递归
检测全部失效（`estimated=unknown(syntax)`），规则校验在算法主场景形同虚设。

---

## 3. 方案：判定分层 + 程序化一致性 + 规则校验补盲

### 3.1 核心思想：把"发现问题"与"是否判错"解耦

重构的出发点是把评估器的判定从一维（正确/错误）拆成两个正交维度：

1. **发现维度**（`findings`）：记录一切可疑点，带 `error_type`（10 类）与
   **`severity`**——这是本次重构新增的关键字段。
2. **裁决维度**（`verdict`）：**只由 `severity == fatal` 的 finding 驱动**；
   `minor` 瑕疵只记录、不驱动非 CORRECT。

每条 `ErrorFinding` 增加 `severity: fatal | minor`：

| severity | 含义 | 对 verdict 的作用 |
|---|---|---|
| `fatal` | 破坏推理链成立性/算法正确性的实质缺陷 | 驱动 `PROCESS_INCORRECT` / `SILENT_FAILURE` / `ANSWER_INCORRECT` |
| `minor` | 不影响推理链成立性的轻微瑕疵（表述笔误/自测文字错/可重建的常规省略/无害背景误述） | **只记录**，不驱动非 CORRECT |

### 3.2 重建测试（所有缺陷判定的总闸）

对每条疑似缺陷，先做**重建测试**：去掉/修复该句后，剩余推理链 + 题面条件 +
领域常识能否**重新推出**该结论？

- **能重建**（缺的是装饰性表述、或省略的是平凡/显然/常规推导）→ `minor`。
  平凡公式/常识（sin30°=1/2、勾股定理、定义直接可推出）**不需要推导**；
- **不能重建**（结论依赖未给出的关键推理，或该步断言本身错误）→ `fatal`。
  解题关键引理（贪心最优性、组合计数、游戏必胜性）仅以"显然/易得"带过
  → 判 `fatal jump`。

这条判据直接回答了 §1 的两难：平凡省略可豁免（重建成功），实质缺陷必检出
（重建失败），并给出了**可复现**的操作标准——它不依赖评审者对某类错误的
主观敏感度。

### 3.3 程序化一致性裁决（不信任 LLM 自觉，用规则兜底）

verdict 最终由**沙盒客观信号 + severity** 程序化裁决（`pipeline._reconcile_verdict`），
分三层：

| 沙盒答案 | findings 含 fatal? | 强制 verdict | 理由 |
|---|---|---|---|
| 正确 | 有 | `SILENT_FAILURE` | 答案对但过程有实质缺陷（任务书 SILENT 场景） |
| 正确 | 无（全 minor/空） | `CORRECT` | 剥离"minor 被提升为过程错"的误报 |
| 错误 | 有 | `PROCESS_INCORRECT` | 答案错 + 过程也有实质缺陷 |
| 错误 | 无 | `ANSWER_INCORRECT` | 仅答案错（沙盒已证伪） |

另有两处程序化兜底：`fatal finding + verdict=CORRECT` 的自相矛盾在 agent 层
强制改正；refine 模式（无沙盒信号）下"全部 findings 为 minor"视同过程正确，
避免对表述瑕疵空转修正轮。

### 3.4 规则校验补盲（任务书"规则校验"手段落地）

`static_check` 作为**独立的实现/结果层审核**（审 solver 产出的代码 artifact，
与 verifier 对推理链文本的过程评估正交），按语言分发：

- **Python**：`ast` 解析（复杂度声明一致性、死循环、递归无终止、边界启发式）；
- **C++**：新增 token 级启发式（P4 补盲）——剔除注释/字符串 → 配对 `{}`/`()`
  → 识别 for/while 块嵌套深度（复杂度粗估）、恒真循环无 break/return（死循环）、
  递归无非递归 return（无终止）。

定位：**不单独阻断 verdict**（启发式有误报，且它不直接判断推理链成立性），
输出作为 verifier 的 `static_evidence` 补充诊断证据。规则黄金样例集与规则配对存放
于 `tests/test_static_check.py`（每条规则含"正例应命中/负例不误报"），开源后
`pytest tests/test_static_check.py` 可直接验证规则行为，便于后续按需扩规则而不影响主判定。

### 3.5 判定流程总览

```
solve → executor(沙盒 answer_correct) → static_check(规则校验，Python+C++，不阻断)
  │                                          │
  └──► verifier V1(自含性) + V2(全局回溯)     └──► static_evidence（补充诊断）
        │ 每条 finding 带 severity + 重建测试
        └─ ARBITER 总仲裁：复核双方判定并交付最终 verdict
           （无论 V1/V2 是否一致；findings 合并保留各自 severity；调用失败 → HUMAN_REVIEW）
        ▼
        _enforce_fatal_consistency（agent：fatal+CORRECT 矛盾 → 强制非 CORRECT）
        ▼
        _reconcile_verdict（pipeline：沙盒信号 + severity 权威裁决）
        ▼
        metrics 双口径：主口径(fatal-only) / 副口径(minor 也计入，env REX_MINOR_AS_ERROR)
```

### 3.6 双口径指标（口径敏感性透明）

- **主口径**（默认）：verdict 由 fatal 驱动——minor 剥离。
- **副口径**：把 minor 瑕疵也计为过程错误（`REX_MINOR_AS_ERROR=1` 一键切换）。

报告与仪表盘并列展示两口径数值，不回避"如果算上微小瑕疵结果差多少"，使口径
敏感性可量化，避免"挑口径"质疑。

---

## 4. 验证

评估器是"测量工具"，必须证明它可靠。沿用题集难度分的方法论（见
`DIFFICULTY_SCORING_METHOD.md`），我们从**误报侧**（答案对但被判过程有错）与
**漏检侧**（答案对且被判正确但实际有 fatal）双向验证。

### 4.1 判定层单元测试（判定语义自洽）

severity 驱动 verdict 的每一条规则均有单测覆盖（`tests/test_severity_consistency.py`
`tests/test_metrics.py` `tests/test_pipeline.py`）：fatal+CORRECT 矛盾强制、
答案对+无 fatal → CORRECT、答案错永不 CORRECT/SILENT、refine 全 minor 视为
正确、副口径分母扩大等，共 97 项测试全通过。

### 4.2 小样本有效性验证（难题区间，误报高发区）

**为何选难题区间**：难度越高，推理链越复杂、实现越易有隐蔽缺陷，误报与漏检
可能性都最高——是评估器可靠性的压力测试区。

**验证方法**：用 severity 版 verifier 对 CF 难题区间（`diff_score ≥ 60`）28 条
记录做 **re-verify**（复用既有 answer，重跑执行/静态/验证，仅重判 verdict），
对比新旧判定。

**结果（28 条，10 条 verdict 变化）**：

| 变化方向 | 题数 | 样本 | 人工核验结论 |
|---|---|---|---|
| 旧过程错 → 新 CORRECT（误报剥离） | 2 | C2106（2 finding 全 minor，纯 selftest 文字笔误）、C2028 | 剥离正确：微小错误不再驱动过程错 |
| 旧 CORRECT → 新 SILENT_FAILURE（漏检补抓） | 3 | C2084（trie 数组 4000005 < 最坏 4100042，缓冲越界）、C2102（声称 O((n+q)α(n)) 实最坏 O(n²)）、C2119（声称 O(N log N) 实 O(n² log n)） | **全部真实 fatal**：答案全对但实现有根本缺陷——正是任务书 SILENT 场景，旧版全漏检 |
| 旧 ANSWER_INCORRECT → 新 PROCESS_INCORRECT（语义细化） | 5 | C2051/C2060/C2110/C2132/C2185 | 更精确：答案错 + 定位到具体 fatal |
| 旧 SILENT_FAILURE 保留 | 1 | C2133（free_ok 分支缺陷，对拍 34/40 mismatch） | 判定稳定且真实 |

**误报率（小样本）**：误报率分母 = 答案正确且被判过程有错的样本（4 条：
C2084/C2102/C2119/C2133）。人工逐条核验：
- C2133：对拍 **34/40 mismatch**（free_ok 分支遗漏）→ 真实；
- C2084：trie 数组大小 < 最坏节点数 → 真实（buffer overflow）；
- C2102 / C2119：复杂度声明与实际实现不符（最坏 O(n²)/O(n² log n)）→ 真实。

**误报率 = 0 / 4 = 0%**（人工核验 4 条全部确认为真实问题，无误报）。
同时新 verifier 还补抓了 3 个旧版漏检的真 SILENT——证明 severity 版**不是靠放宽
判定降低误报，而是在同一判定标准下更精准**。

### 4.3 与人工抽检口径的关系

任务书要求误报率在**答案正确样本**上测（分母=答案对+被判过程有错），经人工
抽检确认真实/误报比例。小样本 4 条 right_pi 全量人工核验；全量 re-verify 后
将基于新 verdict 重新生成抽检层、人工抽检回填，按 `audit_rules.md v3`
（severity 对齐版）标注。

---

## 5. 定位与边界（诚实声明）

- **severity 判定仍由 LLM 给出**（经重建测试引导），程序层只做一致性兜底；
  若 LLM 对某类缺陷的 severity 标注系统性偏差（如把真 fatal 标成 minor），
  程序化裁决无法发现——缓解靠 golden 样本库与人工抽检的漏检侧监控。
- **C++ 静态检测是 token 级启发式**，非完整 parser：复杂度只看循环嵌套（二分的
  `while(l<=r)` 会被估成 O(n)，与 Python 版同局限）、`for(;;)` 死循环可检；
  它定位为 verifier 的参考信号，不单独阻断判定。
- **平凡/显然的边界是判断性的**：重建测试提供操作判据，但"某省略是否可由领域
  常识直接补齐"最终仍需评审者判断——这正是需要人工抽检的原因。
- 本验证为**难题区间小样本**（28 条）；全量 359 条 re-verify 后将以完整数据
  重新报告误报率/定位准确率与分层结果。

---

## 附：执行与复现

```bash
# 判定层改动
#   src/rex/models.py                 ErrorSeverity(fatal/minor) + ErrorFinding.severity
#   src/rex/verifier/prompts.py       重建测试判据 + severity 输出要求
#   src/rex/verifier/agent.py         fatal+CORRECT 矛盾程序化改正
#   src/rex/pipeline.py               _reconcile_verdict（沙盒+severity 权威裁决）
#   src/rex/refine/{agent,prompts}.py 仅 fatal 驱动修正（minor 不空转）
#   src/rex/executor/static_check.py  C++ 复杂度/死循环/递归检测补盲
#   src/rex/metrics/compute.py        主/副双口径

# 单元测试
python -m pytest tests/

# 小样本 re-verify（难题区间）
python -m src.cli re-verify --results data/outputs/eval_cf_all.jsonl \
    --diff-min 60 --out data/outputs/reverify_cf_hard.jsonl

# 全量 re-verify（ABC + CF）
python -m src.cli re-verify --results data/outputs/eval_cf_all.jsonl \
    --out data/outputs/eval_cf_all.reverified.jsonl
python -m src.cli re-verify --results data/outputs/eval_selfbuilt_all.jsonl \
    --out data/outputs/eval_selfbuilt_all.reverified.jsonl
```

**方法论要点速览**：不把"任何瑕疵"当过程错（误报爆炸）→ 不信任 LLM 自洽
（自相矛盾无法兜底）→ 用 **severity(fatal/minor) + 重建测试**把"发现"与"判错"
解耦，平凡省略可豁免、实质缺陷必检出 → 沙盒+severity **程序化一致性裁决** →
规则校验（规则校验=实现/结果层审核，与过程评估正交，Python+C++ 双语，不阻断）→
双口径透明报告 → 难题区间小样本验证（误报率 0/4，另补抓 3 个旧漏检真 SILENT）
→ 全量 re-verify。

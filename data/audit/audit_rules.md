# 人工抽检员判定规则（v4，2026-09-08 三层复核口径）

> 用途：抽检员对「系统 verifier 的判定」进行独立复核，产出
> verdict_human / error_step_id / error_type_human / human_severity_match / note
> （本规则为抽检工作底稿，抽检员按此执行并回填标注）。
> 本规则独立于 verifier 审查 prompt，不随 verifier 修改而变（保持裁判独立性）。

## 角色
- 审的是：系统对某题解题过程的判定（verdict + findings + fatal/minor 分级）准不准
- 拥有地面真相：标准答案、参考解、逐用例「期望输出 vs AI 实际输出」（含隐藏用例）
- 不审 AI 解题本身，只评估系统判定；但需读 AI 过程与代码才能判断系统说得对不对

## A. 客观事实层（不争论，以用例为准）
1. 答案正确性以沙盒逐用例事实为准：公开+隐藏用例输出与期望全部一致
   （浮点看容差；SPJ 看 checker 判定）→ 答案对；否则答案错。
   代码整体正确性 = answer_correct（沙盒判），**不是 process fault 的来源**。

## B. process fault 精确定义（用户裁决版）
process fault = 推理过程中的错误，含两类：
   B1 **题意误读/概念/计算/逻辑等推理错误**：即使代码碰巧能处理（如误读"无重边"但
      邻接表能处理多重边、用例全过），误读题面约束本身仍是过程错误 → PROCESS_INCORRECT。
      不因代码健壮/用例全过而豁免。
   B2 **推理与代码不符 / 代码中间的错误**：文字描述的算法与实现不一致（如 approach
      写"移动 k-1 次"而代码循环 k 次），或代码存在潜在缺陷（如类型窄化）只是测试
      用例不够巧妙未覆盖 → PROCESS_INCORRECT / SILENT_FAILURE。不能以"测试没抓到"为由豁免。

3. 代码有失败用例 → 必定位：失败根因能追溯到第几步（建模/推导/实现），就标那步。
   此时答案错 → 判 ANSWER_INCORRECT 或 PROCESS_INCORRECT（视过程是否也有错）。

4. 跳步判定（与 verifier 方案 B 一致）：
   - 常识/定义值（sin30°=1/2、勾股定理、质数定义）直接引用 → 不算 jump
   - 关键中间结论仅以「显然/易得」带过、无推导且直接支撑答案 → 算 jump

## C. 三层复核（human_severity_match，核心字段）

**复核对象是系统打的分级（fatal/minor）是否属实**——即系统把缺陷判成什么级别、
以及据此给出的 verdict 是否站得住。对「系统判过程有错（PROCESS_INCORRECT /
SILENT_FAILURE）」的样本，人工对照真实缺陷后给三层结论：

| human_severity_match | 含义 | 误报率归属 |
|---|---|---|
| `match`（完全相符） | 系统 fatal/minor 分级正确（确有 fatal 驱动其判定） | 非误报（主/副口径均不计） |
| `level_mismatch`（层次不符） | 方向对但分级打反：系统把 minor 判成 fatal（或其判定由过严分级驱动） | 主口径误报（minor 不算过程错）；副口径不计 |
| `fp`（完全不符） | 系统说有错但实际过程正确（无 B1/B2 缺陷） | 主/副口径均误报 |

对「系统判 CORRECT」的样本：人工复核若发现被 minor 化的 fatal → 漏检
（verdict_human 标错、note 说明；单独记录，不进误报率分母）。

> 旧字段 is_false_positive / human_error_severity 已弃用（v4 前标注仅兼容读取）。

## D. 保守与可追溯
7. 拿不准不判错：证据不足以确证缺陷时，倾向跟随客观事实（答案对就尽量不判过程错）。
   拿不准的样本：交给用户裁决，或开 2 个独立 agent 讨论后取结论。
8. 每条判定写证据：引用具体用例输出（期望 vs 实际）或具体步骤内容。

## E. severity 分级（判定器如何打标，抽检时用来对照）
系统每条 finding 现带 severity：
- **fatal**（实质缺陷）：推理链断裂/关键引理未证且不可重建、误用定理、循环论证、
  逻辑缺陷、推理与代码实质不符、漏处理会致错的条件。**只有 fatal 才驱动
  PROCESS_INCORRECT/SILENT_FAILURE 判定**。
- **minor**（轻微瑕疵）：表述笔误、自测文字错误、可重建的常规论证省略、
  复杂度叙述不精确但结论仍成立、无害背景误述。**minor 不驱动非 CORRECT**。

人工三层复核即对照此分级：系统所判 fatal 经人工核验确为 fatal → match；
实为 minor 或可重建 → level_mismatch（打反）；根本无缺陷 → fp。

## F. 已确认口径（用户逐条裁决）
- E1 误读题面约束（如称"无重边"实为 multi-edges）= 过程错误，判 PROCESS_INCORRECT；
  代码恰好健壮、用例全过不豁免（A1013 即此情形）
- E2 推理文字与实现不符（如 off-by-one 描述）= 过程推理错误，判 PROCESS_INCORRECT
  （A1024 即此情形）；若存在会让"某组数据出错"的潜在缺陷，即使测试未覆盖也成立
- E3 答案全对 + 代码全过 + 无 B1/B2 缺陷 → CORRECT → human_severity_match 无需填
  （仅判 CORRECT 的对照/漏检样本需填 note）
- E4 拿不准 → 交用户/双 agent 讨论；证据不足不判错
- E5 **关键引理需证明**：贪心最优性、组合计数公式、游戏必胜性等解题关键结论
  仅以"显然/易得/等价于已知结论"带过 → 算 fatal jump（用户裁决：非显然必须推导）
- E6 **平凡公式/常识不需推导**：定义值（sin30°=1/2）、公理级性质（勾股定理）、
  直接定义可推出的步骤 → 不算 jump，即使未展开推导

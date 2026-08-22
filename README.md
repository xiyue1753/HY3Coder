# ReAgents v2 — 可验证场景的过程评估与错误定位系统

犀牛鸟实战任务 2 参赛作品。面向算法编程与数学解题两个可验证场景，构建"**分步求解 → 过程评估 → 错误定位归类 → 自我修正**"的完整闭环：给定一道题，系统产出结构化分步过程，自动判定推理链是否成立、定位错误起始步骤、归纳错误类型，并识别"**答案正确但过程不成立**"的沉默失败样本；验证反馈可回流驱动求解 Agent 迭代修订（ReAct 闭环），实现从"评测器"到"评测 + 增强"的应用闭环。

## 核心能力

| 能力 | 说明 |
|---|---|
| 大规模分层题集 | 算法 707（TACO/CodeContests）+ 数学 326（MATH），按基础/中等/困难三档分层，附来源与可复现分层规则 |
| 分步求解 | 求解 Agent 产出结构化分步过程（每步含结论与前置依赖），算法场景自动提取可执行代码 |
| 过程评估 | 逐步自含性检查 + 全局回溯两轮审查；两个独立验证视角交叉复核，不一致时仲裁 |
| 错误定位归类 | 6 类基线（题意误读/概念错误/计算错误/条件遗漏/跳步推导/格式不符）+ 场景扩展（逻辑缺陷/边界条件/复杂度不达标） |
| 沉默失败识别 | 人工构造 golden 样本库（算法 15 + 数学 8，附构造说明），验证"答案对但过程错"的检出能力 |
| ReAct 自我修正 | eval 模式（一次性、反馈绝不回流，保证指标可信）+ refine 模式（反馈→修订→重验证，限 3 轮收敛） |
| 可自动校验 | 数学精确比对标准答案；算法沙盒执行公开+隐藏测试用例，复杂度/边界静态检查 |
| 量化评估 | 答案准确率/过程正确率/定位命中率/误报率 + Wilson 置信区间 + 抽样稳定性验证 |
| 可视化仪表盘 | FastAPI + 单文件 SPA：评估总览、单题过程回放（错误步骤红框+修正轮次切换）、golden 库、人工抽检、交互式解题 |

## 快速开始

```bash
# 1. 依赖（Python 3.13）
pip install -r requirements.txt

# 2. 配置 Hy3 接入（复制并填写密钥，.env 已被 .gitignore 排除）
copy .env.example .env
#    HY3_API_KEY=...   HY3_BASE_URL=https://tokenhub.tencentmaas.com/v1   HY3_MODEL=hy3

# 3. 端到端 demo（数学 3 题 / 算法 5 题）
python -m src.cli run-eval --scene math --sample 5
python -m src.cli run-eval --scene algorithm --sample 5

# 4. 放大评估（主 3 档 × 100）
python -m src.cli run-eval --scene math --sample 100 --resume
python -m src.cli run-eval --scene algorithm --sample 100 --resume

# 5. 修正模式（ReAct 闭环演示）
python -m src.cli run-refine --scene math --sample 5

# 6. 答案校验 / 人工抽检 / 仪表盘
python -m src.cli check-answers --results data/outputs/eval_math.jsonl
python -m src.cli audit --results data/outputs/eval_math.jsonl --sample 30
python -m src.cli serve        # 打开 http://127.0.0.1:8000

# 7. 测试
python -m pytest tests/
```

`--sample` 支持 `5 / 10 / 50 / 100 / full`，抽样种子固定（默认 42）保证可复现；`--resume` 断点续跑。

## 双模式与数据纯净性

- **eval 模式**：一次性完成 `solve → execute → verify`，验证反馈**绝不回流**给求解器，指标只基于 eval 数据。
- **refine 模式**：将 `VerificationResult.findings` 映射为可操作修订指令（定位 step_id + 错误类型 + 证据）→ 求解 Agent 修订 → 重验证，限 3 轮，记录每轮收敛轨迹。两模式结果严格分离存储（`data/outputs/eval_*.jsonl` / `refine_*.jsonl`）。

## Hy3 的角色

- 求解 Agent：将题目转换为分步求解 JSON（数学 derive/calc/check；算法 understand/approach/complexity/implement/selftest）。
- 验证 Agent × 2：独立完成自含性检查与全局回溯，交叉复核。
- 仲裁 Agent：双视角不一致时最终裁定。
- 模型调用经迁移自旧版 `Hy3_APP/src/ctxpilot/hy3/client.py` 的 `Hy3Client`（OpenAI 兼容接口，重试退避、流式、reasoning_effort、防注入 guard prompt）。

## 数据来源与许可

| 数据集 | 来源 | 许可 |
|---|---|---|
| TACO（算法） | agentica-org/DeepCoder-Preview-Dataset | Apache-2.0 |
| CodeContests（算法） | 同上 | Apache-2.0 |
| MATH（数学） | HuggingFaceH4/MATH | MIT |

题集（`data/questions/*.jsonl`）由上述数据集经 HuggingFace datasets 加载、字段归一化与三档分层后入库，含标准答案与分层依据，可复现（`scripts/build_questions.py`）。Golden 沉默失败样本为人工构造，`data/golden/`。

## 目录结构

```
Hy3_APP2/
├── DESIGN.md                # 正式设计文档（分层规则表/错误分类/schema 契约/双模式）
├── README.md
├── requirements.txt
├── .env.example             # Hy3 接入样例（真实密钥存 .env，不入库）
├── src/rex/
│   ├── hy3_client.py  config.py  models.py  pipeline.py
│   ├── datasets/  loader.py  sampling.py  schema.py
│   ├── solver/    agent.py  prompts.py
│   ├── verifier/  agent.py  prompts.py  errors.py
│   ├── refine/    agent.py  prompts.py
│   ├── executor/  sandbox.py  tests.py  static_check.py
│   └── metrics/   compute.py  stats.py
├── src/web/  api.py  static/index.html      # FastAPI 仪表盘
├── src/cli.py                               # typer 入口
├── data/questions/  algorithm.jsonl(707) math.jsonl(326)
├── data/golden/     golden_algorithm.jsonl(15) golden_math.jsonl(8)
├── data/outputs/    eval/refine 结果 + audit_records.jsonl
├── scripts/         build_questions.py build_golden.py audit_sample.py check_answers.py
├── reports/         分析报告 + demo 脚本
└── tests/           pytest（FakeHy3 + 沙盒隔离 + refine 闭环）
```

## 评估指标口径

- **答案准确率**：数学 = 标准答案精确比对；算法 = 沙盒运行公开+隐藏用例通过率 ≥1。
- **过程正确率**：verdict=CORRECT 占比（验证 Agent×2+仲裁）。
- **错误定位命中率 / 误报率**：基于人工抽检标注（`scripts/audit_sample.py` 生成模板）。
- **沉默失败检出率**：golden 样本中判定 SILENT_FAILURE 占比。
- 指标附 **Wilson 95% 置信区间**与**同档二次抽样稳定性验证**。

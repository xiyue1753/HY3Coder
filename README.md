# HY3Coder — 可验证算法场景的过程评估与错误定位系统

犀牛鸟开源实战任务 2 参赛作品（个人/活动作品）。面向**算法竞赛**可验证场景，构建"**分步求解 → 过程评估 → 错误定位归类 → 自我修正**"的完整闭环：给定一道算法竞赛题，系统产出结构化分步求解过程，自动判定推理链是否成立、定位错误起始步骤、归纳错误类型，并识别"**答案正确但过程不成立**"的沉默失败样本；验证反馈可回流驱动求解 Agent 迭代修订（ReAct 闭环），实现从"评测器"到"评测 + 增强"的应用闭环。本仓库为个人参赛作品，非腾讯官方发布。方案聚焦**算法竞赛**可验证场景。

## 核心能力

| 能力 | 说明 |
|---|---|
| 大规模分层题集 | 自建 AtCoder ABC 175 题（主推）+ Codeforces 自建 184 题（含 GitHub 公开题解源），按基础/中等/困难三档分层，附来源与可复现分层规则 |
| 分步求解 | 求解 Agent 产出结构化分步过程（每步含结论与前置依赖），自动提取可执行代码 |
| 过程评估 | 逐步自含性检查 + 全局回溯两轮审查；两个独立验证视角 + ARBITER 总仲裁交付最终结果 |
| 错误定位归类 | 6 类基线（题意误读/概念错误/计算错误/条件遗漏/跳步推导/格式不符）+ 算法扩展（逻辑缺陷/边界条件/复杂度不达标） |
| 沉默失败识别 | 评估器在自然评测中识别"答案对但过程根本缺陷"（SILENT_FAILURE）并留档核验 |
| ReAct 自我修正 | eval 模式（一次性、反馈绝不回流，保证指标可信）+ refine 模式（反馈→修订→重验证，限 3 轮收敛） |
| 可自动校验 | 算法沙盒执行公开+隐藏测试用例（Python/C++ 自动检测、SPJ 判题），复杂度/边界/死循环静态检查 |
| 量化评估 | 答案准确率/过程正确率/定位命中率/误报率 + Wilson 置信区间 + 抽样稳定性验证 |
| 可视化仪表盘 | FastAPI + 单文件 SPA：评估总览、单题过程回放（错误步骤红框+修正轮次切换）、golden 库、人工抽检、交互式解题 |

## 环境要求

> 系统 `python` 是 WindowsApps 占位程序（调用会报 exit 9009），**不可用**。
> 解释器优先级：① **`tensor_env`**（Python 3.9，推荐，run.ps1 默认）
> ② anaconda base（Python 3.13，备选）。两者均已装好依赖。

```powershell
# 1. 创建并激活 conda 环境（若尚未创建）
conda create -n tensor_env python=3.9 -y
conda activate tensor_env
pip install -r requirements.txt
```

> 说明：代码使用了 `X | None` 等 3.10+ 类型注解语法，在 Python 3.9 下依赖
> `eval_type_backport`（已写入 requirements.txt）求值。

**推荐用仓库自带的 `run.ps1` 统一调用**（默认 tensor_env；备选 anaconda 时
设 `$env:REX_PYTHON="D:\ProgramData\anaconda3\python.exe"` 覆盖）：

```powershell
.\run.ps1 test              # 运行全部 pytest
.\run.ps1 run-eval algorithm 5  # 评估算法 5 题
.\run.ps1 report            # 生成报告
.\run.ps1 serve             # 启动仪表盘
```

## 快速开始

```bash
# 1. 依赖（推荐 conda 环境 tensor_env，Python 3.9）
pip install -r requirements.txt

# 2. 配置 Hy3 接入（复制并填写密钥，.env 已被 .gitignore 排除）
copy .env.example .env
#    HY3_API_KEY=...   HY3_BASE_URL=https://tokenhub.tencentmaas.com/v1   HY3_MODEL=hy3

# 3. 端到端 demo（算法 5 题）——用 run.ps1 或 tensor_env 的 python
.\run.ps1 run-eval algorithm 5

# 4. 放大评估（主 3 档 × 100，断点续跑 + 并发）
.\run.ps1 exec -m src.cli run-eval --scene algorithm --sample 100 --resume --concurrency 4

# 5. 修正模式（ReAct 闭环演示）
.\run.ps1 run-refine algorithm 5

# 6. 答案校验 / 人工抽检 / 仪表盘
.\run.ps1 exec -m src.cli check-answers --results data/outputs/eval_abc_selfbuilt_t0.jsonl
.\run.ps1 exec -m src.cli audit --results data/outputs/eval_abc_selfbuilt_t0.jsonl --sample 30
.\run.ps1 serve        # 打开 http://127.0.0.1:8000

# 7. 自建 AtCoder ABC 题集评测 / 抽检（真实 Hy3 调用）
.\run.ps1 exec -m src.cli run-eval --questions abc_selfbuilt.jsonl --sample full --resume --concurrency 4
.\run.ps1 exec -m src.cli audit --results data/outputs/eval_abc_selfbuilt_t0.jsonl --questions data/questions/abc_selfbuilt.jsonl --sample 30

# 8. 测试
.\run.ps1 test
```

`--sample` 支持 `5 / 10 / 50 / 100 / full`，抽样种子固定（默认 42）保证可复现；`--resume` 断点续跑。
正式基线为 **temperature=0 全量重跑结果 `data/outputs/eval_abc_selfbuilt_t0.jsonl`**（文件位置由数据源注册中心
`src/rex/datasource.py` 统一声明，`--out` 可覆盖）。

## 双模式与数据纯净性

- **eval 模式**：一次性完成 `solve → execute → verify`，验证反馈**绝不回流**给求解器，指标只基于 eval 数据。
- **refine 模式**：将 `VerificationResult.findings` 映射为可操作修订指令（定位 step_id + 错误类型 + 证据）→ 求解 Agent 修订 → 重验证，限 3 轮，记录每轮收敛轨迹。两模式结果严格分离存储（`data/outputs/eval_*.jsonl` / `refine_*.jsonl`）。

## Hy3 的角色

- 求解 Agent：将题目转换为分步求解 JSON（算法 understand/approach/complexity/implement/selftest）。
- 验证 Agent × 2：独立完成自含性检查与全局回溯，交叉复核。
- 仲裁 Agent：双视角不一致时最终裁定。
- 模型调用经迁移自旧版 `Hy3_APP/src/ctxpilot/hy3/client.py` 的 `Hy3Client`（OpenAI 兼容接口，重试退避、流式、reasoning_effort、防注入 guard prompt）。

## 数据来源与许可

| 数据集 | 来源 | 许可 |
|---|---|---|
| TACO（算法·公开对照） | agentica-org/DeepCoder-Preview-Dataset | Apache-2.0 |
| CodeContests（算法） | 同上 | Apache-2.0 |
| 自建 AtCoder ABC（算法·主推） | AtCoder ABC 比赛原题 + AC 参考解 | 数据版权归 AtCoder，仅供研究 |

题集（`data/questions/*.jsonl`）：
- **自建集 `abc_selfbuilt.jsonl`（AtCoder ABC 175 题，主推）**：由独立产线抓题面 + AC 参考解 + 人工设计隐藏边界用例入库，难度按 ABC 分值映射三档（basic34/medium82/hard59），含 SPJ 多解构造题（checker 判题）；
- **自建集 `cf_selfbuilt.jsonl`（Codeforces 184 题，与 ABC 大致同规模）**：同产线，参考解来自 CF 公开 AC 提交与 GitHub 公开题解仓库（绕开 CF 反爬的提交页限流，题目页抓取 + GitHub 解样例沙盒验证），分层 basic34/medium83/hard67；
- TACO/CodeContests 公开镜像题集曾以 `algorithm.jsonl` 命名，2026-09 起废弃该命名（数据隔离，未来按独立数据集如 `taco` 注册），不再进入仪表盘/统计；
- SILENT_FAILURE 由真实评测检出并留档核验：逐题判定、findings 与沙盒事实随评测结果 `data/outputs/eval_*_t0.jsonl` 一并交付，可复现报告中的检出与抽检结论。
- **数据文件位置统一由注册中心 `src/rex/datasource.py` 声明。**

## 目录结构

```
Hy3_APP2/
├── DESIGN.md                # 正式设计文档（分层规则表/错误分类/schema 契约/双模式）
├── README.md
├── requirements.txt
├── .env.example             # Hy3 接入样例（真实密钥存 .env，不入库）
├── src/rex/
│   ├── datasource.py  # 数据源注册中心（唯一权威，改数据源只动这里）
│   ├── hy3_client.py  config.py  models.py  pipeline.py
│   ├── datasets/  loader.py  sampling.py  schema.py
│   ├── solver/    agent.py  prompts.py
│   ├── verifier/  agent.py  prompts.py  errors.py
│   ├── refine/    agent.py  prompts.py
│   ├── executor/  sandbox.py  tests.py  static_check.py
│   └── metrics/   compute.py  stats.py
├── src/web/  api.py  static/index.html      # FastAPI 仪表盘
├── src/cli.py                               # typer 入口
├── data/questions/  abc_selfbuilt.jsonl(175) cf_selfbuilt.jsonl(184)
├── data/outputs/    eval_abc_selfbuilt_t0.jsonl(175, ABC) + eval_cf_selfbuilt_t0.jsonl(184, CF)
│                    + refine_wrong_t0.jsonl(36) + contamination_probe.jsonl(30) + diff_scores.jsonl(359)
│                    （正式结果随仓库交付；运行日志与历史分片不入库，见 .gitignore）
├── scripts/         评测主流程与数据可再生脚本
│                    evaluate.py check_answers.py refine_failed.py make_report.py
│                    gen_hidden_cases.py gen_cf_hidden_cases.py normalize_tags.py 等
├── reports/         分析报告（REPORT.md 与方法论文档）
└── tests/           pytest（FakeHy3 + 沙盒隔离 + refine 闭环）
```
方案文档见 `方案文档.md`；任务与设计文档见 `DESIGN.md`。
（数据抓取/实现过程等内部文档不随公开仓库发布，仅本地保留。）
```

## 评估指标口径

- **答案准确率**：算法 = 沙盒运行公开+隐藏用例通过率 ≥1（无测试用例时按标准答案文本比对）。
- **过程正确率**：verdict=CORRECT 占比（验证 Agent×2+仲裁）。
- **错误定位命中率 / 误报率**：基于人工抽检标注（`scripts/audit_sample.py` 生成模板）。
- **沉默失败检出**：自然评测中判定 SILENT_FAILURE 的样本数与占比（识别"答案对但过程根本缺陷"）。
- 指标附 **Wilson 95% 置信区间**与**同档二次抽样稳定性验证**。

**过程判定 severity 口径**：每条 finding 带 `fatal`（实质缺陷，驱动非 CORRECT）或
`minor`（表述瑕疵，不驱动非 CORRECT）。默认**主口径**=仅 fatal 计入过程错；
设置环境变量 `REX_MINOR_AS_ERROR=1` 可一键切到**副口径**（minor 也计入），
报告与仪表盘均按此开关展示（`src/rex/config.py`）。规则校验（复杂度/死循环/
边界，Python+C++）属**实现/结果层审核**，不单独阻断 verdict，其黄金样例集与
规则配对存放于 `tests/test_static_check.py`（`pytest tests/test_static_check.py`
可直接验证规则行为）。

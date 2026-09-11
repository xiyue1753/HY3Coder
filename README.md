# HY3Coder — 可验证算法场景的过程评估与错误定位系统

犀牛鸟开源实战任务 2 参赛作品（个人/活动作品）。面向**算法竞赛**可验证场景，构建"**分步求解 → 过程评估 → 错误定位归类 → 自我修正**"的完整闭环：给定一道算法竞赛题，系统产出结构化分步求解过程，自动判定推理链是否成立、定位错误起始步骤、归纳错误类型，并识别"**答案正确但过程不成立**"的沉默失败样本；验证反馈可回流驱动求解 Agent 迭代修订（ReAct 闭环），实现从"评测器"到"评测 + 增强"的应用闭环。本仓库为个人参赛作品，非腾讯官方发布。方案聚焦**算法竞赛**可验证场景。

> **分析报告（交付正文）**：[`REPORT.md`](REPORT.md) —— 359 题正式基线的指标与置信区间、分层退化、错误定位与修正效果，含附录 A–D 四份方法文档全文。
> 网页版 [`reports/REPORT.html`](reports/REPORT.html)，排版更适合阅读与打印；四份方法文档也以单篇形式并列存放在 `reports/` 下。
> **演示录像**：[`HY3Coder-demo.mp4`](HY3Coder-demo.mp4)（79 秒 / 1920×1080）。

**核心读数**（359 题全量评测，temperature=0，每题一次求解）：

- 答案准确率 **90.0%**；过程正确率 **84.4%**，95% CI [80.3%, 87.8%]
- 识别出「答案全对、用例全过，过程仍有致命缺陷」的 `SILENT_FAILURE` 样本 **15 条（4.2%）**
- 评估器有效性经人工抽检：答案错样本的缺陷定位准确率 **96.6%**；被判过程有错样本的误报率 **5.3%–10.5%**（48 条分层抽检全量回填，争议逐条终审）
- 难度轴为自建统一难度分，与平台官方 ELO 的 Spearman 秩相关 **ABC 0.706 / CF 0.816**；过程正确率随难度单调下降，中等档起显著失守（93.7% → 62.9%）
- 修正闭环：答案错的 36 题限 3 轮内 **77.8%** 收敛，最终 27 题答案正确

## 交付材料索引（对应任务书第 2 项）

任务书要求与产出的逐条落点如下；报告正文 §1.2 另有一份"任务要求 → 系统对应"的对照表。

| 任务书要求 | 交付材料 | 位置 |
|---|---|---|
| 开源仓库：应用源码 | 求解 / 验证 / 修正 / 执行 / 指标各层模块、CLI 与 FastAPI 仪表盘 | `src/rex/`、`src/web/`、`src/cli.py` |
| 开源仓库：过程评估模块 | 双视角验证 + 总仲裁、沙盒执行与静态检查、指标与统计 | `src/rex/verifier/`、`src/rex/executor/`、`src/rex/metrics/` |
| 开源仓库：README、环境配置样例与运行说明 | 环境要求、快速开始、统一运行入口与目录说明 | `README.md`、`.env.example`、`requirements.txt`、`run.ps1` |
| 评测材料：分层题集及标准答案 | 两套自建集，每题含题面、平台 AC 参考解、公开 + 隐藏用例、判题模式与分层依据 | `data/questions/abc_selfbuilt.jsonl`（175）、`data/questions/cf_selfbuilt.jsonl`（184） |
| 评测材料：分层依据 | 统一难度分的方法论文档与逐题打分明细 | `reports/DIFFICULTY_SCORING_METHOD.md`、`data/outputs/diff_scores.jsonl` |
| 评测材料：答案校验脚本 | 在沙盒里跑公开 / 隐藏用例，多解题目走 SPJ checker | `scripts/check_answers.py`、`src/rex/executor/judge.py` |
| 评测材料：过程评估脚本 | 逐题走「求解 → 沙盒 → 双视角验证 + 仲裁」 | `scripts/evaluate.py`、`src/rex/verifier/` |
| 完整结果：最终答案准确率、过程正确率 | 359 题全量读数、Wilson 区间与抽样稳定性检验 | `REPORT.md` §1；逐题明细 `data/outputs/eval_abc_selfbuilt_t0.jsonl`、`data/outputs/eval_cf_selfbuilt_t0.jsonl` |
| 完整结果：错误类型分布 | 10 类错误的分布与典型证据 | `REPORT.md` §3 |
| 完整结果：难度分层结果 | 统一难度轴上的分层退化，指出明显下降的难度区间 | `REPORT.md` §2 |
| 有效性验证：定位准确率与误报率 | 答案错的 29 条全量复核、答案对却判过程有错的 19 条三层复核 | `REPORT.md` §6 |
| 有效性验证：人工抽检记录 | 48 条抽检标注、抽检规则与抽样模板 | `data/audit/audit_records.jsonl`、`data/audit/audit_rules.md`、`scripts/audit_sample.py` |
| 分析报告：设计依据、错误分类体系、典型案例、能力边界与临界点 | 正文 §1–§9，附录 A–D 为四份方法文档全文 | `REPORT.md`；网页版 `reports/REPORT.html`；单篇 `reports/DIFFICULTY_SCORING_METHOD.md`、`reports/PROCESS_EVAL_METHOD.md`、`reports/REACT_METHOD.md`、`reports/CONTAMINATION_METHOD.md` |
| demo 视频（2 分钟以内） | 79 秒 / 1920×1080，现场演示：题集载入 → 参考解沙盒试运行 → 逐步求解 → 过程评估 | `HY3Coder-demo.mp4` |

提交方式相关的几条：真实密钥不入库（`.env.example` 只列变量名，密钥在本地 `.env`，已被 `.gitignore` 排除）；模型能力调用统一走 Hy3（`src/rex/hy3_client.py`）；README 首段已标注为个人参赛作品。

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

Python 3.9+。代码使用了 `X | None` 等 3.10+ 类型注解语法，在 3.9 下依赖
`eval_type_backport`（已写入 requirements.txt）求值。

```powershell
# 1. 创建并激活 conda 环境（若尚未创建）
conda create -n tensor_env python=3.9 -y
conda activate tensor_env
pip install -r requirements.txt
```

**推荐用仓库自带的 `run.ps1` 统一调用**（默认 `tensor_env`；解释器不叫这个
名字或不在 PATH 上时，用 `$env:REX_PYTHON` 指向自己的 python 覆盖）：

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

## 交互式解题工作台（仪表盘「交互式解题」页）

现场演示一条完整链路：**题目（题集自带参考解）→ 试运行验证用例 → 模型求解 → 过程评估**。
演示/试跑的完整准备清单（环境自检、数据清单、四步脚本、常见问题、已知限制）见
`docs/DEMO_RUN_GUIDE.md`（内部开发文档，同 `docs/` 其余文档一样不入公开仓库）。

- **从题集载入**：选题后自动填好题面、公开样例与该题**自带参考解**（标准答案随请求一并带上，回放页可见；
  隐藏用例只报数量——这是接口层的口径，题集文件里按评测需要带全量用例）；
- **参考解试运行**：在沙盒里跑这段代码，逐用例回显输入 / 期望 / 实际输出与耗时，用来证明用例自洽（C++ 只编译一次后复用，8 个用例约 2 秒）；
- **模型调用配置**（侧栏「模型配置」）：提供方 / API Key / Base URL / Model / 推理强度 / 温度 / 超时，
  可「测试连接」探活。默认 Hy3（腾讯 TokenHub）；Key 只写本地 `.env`（已 gitignore），接口只回显掩码、留空即保持原值。
  页面顶部与求解进度里都会显示**本次调用的是哪个模型**，方便录屏与复现；未配置时求解入口直接拦住并提示。
- **过程评估**：求解完成后展示逐步骤卡片（出错步骤标红）、verdict 与 findings；勾选「演示修正闭环」则走 ReAct 多轮修正。
- **逐 Step 流式**：求解过程不是憋到最后一次性出现——模型边生成边显示，
  步骤卡片依次冒出来、当前步正文实时增长（末步带光标），思考阶段则显示"已思考 N 字"。
  流式只在交互演示启用（`on_step` / `on_reasoning`），正式评测仍走整段调用，口径不变。
- **永久留档**：每次求解都会分配一个新题号（`IX0001`…）并留档——题面/用例/参考解落
  `data/questions/interactive.jsonl`，完整会话快照（含命中模型、参考解试运行逐用例结果、判定摘要）
  落 `data/outputs/interact_sessions.jsonl`，判定记录落 `data/outputs/eval_interactive.jsonl`。
  求解完成后页面上直接给出题号与链接，可在「单题回放」（来源筛选 `interactive`）里按题号回看；
  这些记录与正式评测物理分离，不进任何统计口径。

## 双模式与数据纯净性

- **eval 模式**：一次性完成 `solve → execute → verify`，验证反馈**绝不回流**给求解器，指标只基于 eval 数据。
- **refine 模式**：将 `VerificationResult.findings` 映射为可操作修订指令（定位 step_id + 错误类型 + 证据）→ 求解 Agent 修订 → 重验证，限 3 轮，记录每轮收敛轨迹。两模式结果严格分离存储（`data/outputs/eval_*.jsonl` / `refine_*.jsonl`）。

## Hy3 的角色

- 求解 Agent：将题目转换为分步求解 JSON（算法 understand/approach/complexity/implement/selftest）。
- 验证 Agent × 2：独立完成自含性检查与全局回溯，交叉复核。
- 仲裁 Agent：双视角不一致时最终裁定。
- 模型调用统一由 `Hy3Client` 封装（OpenAI 兼容接口：重试退避、SSE 流式、`reasoning_effort`、防注入 guard prompt）。

## 数据来源与许可

| 数据集 | 来源 | 许可 |
|---|---|---|
| 自建 AtCoder ABC（算法·主推） | AtCoder ABC 比赛原题 + AC 参考解 | 数据版权归 AtCoder，仅供研究 |
| 自建 Codeforces | Codeforces 比赛原题 + 公开 AC 解（含 GitHub 公开题解源） | 数据版权归 Codeforces，仅供研究 |

题集（`data/questions/*.jsonl`）：
- **自建集 `abc_selfbuilt.jsonl`（AtCoder ABC 175 题，主推）**：由独立产线抓题面 + AC 参考解 + 人工设计隐藏边界用例入库，难度按 ABC 分值映射三档（basic34/medium82/hard59），含 SPJ 多解构造题（checker 判题）；
- **自建集 `cf_selfbuilt.jsonl`（Codeforces 184 题，与 ABC 大致同规模）**：同产线，参考解来自 CF 公开 AC 提交与 GitHub 公开题解仓库（绕开 CF 反爬的提交页限流，题目页抓取 + GitHub 解样例沙盒验证），分层 basic34/medium83/hard67；
- SILENT_FAILURE 由真实评测检出并留档核验：逐题判定、findings 与沙盒事实随评测结果 `data/outputs/eval_*_t0.jsonl` 一并交付，可复现报告中的检出与抽检结论。
- **数据文件位置统一由注册中心 `src/rex/datasource.py` 声明。**

## 目录结构

```
Hy3_APP2/
├── REPORT.md                # 分析报告交付副本（正文 §1-§9 + 附录 A-D；权威版本在 reports/REPORT.md）
├── HY3Coder-demo.mp4        # 演示录像 79 秒（任务书要求的 demo 视频）
├── 方案文档.md              # 项目方案书（目标/设计/三大部分/完成度）
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
│                    evaluate.py check_answers.py refine_failed.py
│                    make_report_html.py（把报告渲染成网页版）
│                    gen_hidden_cases.py gen_cf_hidden_cases.py normalize_tags.py 等
├── reports/         分析报告：REPORT.md（正文 §1-§9 + 附录 A-D 四份方法文档全文）
│                    REPORT.html 为同内容网页版；figures/ 正文配图
│                    四份方法文档以单篇形式并列存放，供单独分发
└── tests/           pytest（FakeHy3 + 沙盒隔离 + refine 闭环）
```
方案文档见 `方案文档.md`；任务与设计文档见 `DESIGN.md`。
（数据抓取/实现过程等内部文档不随公开仓库发布，仅本地保留。）

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

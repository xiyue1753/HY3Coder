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

## 任务 dashboard-fix：界面 bug 修复 + 亮暗主题切换（计划外，用户临时插入）

**状态**：✅ 已完成

### 背景
用户在确认仪表盘时发现三类问题：① 枚举标签显示 `undefined`；② 配色与 Hy_APP 不一致；③ 需支持亮/暗主题切换（Hy_APP 有）。

### 目标
修复前端枚举 `.value` 误用导致的 `undefined` 标签；参照 Hy_APP 引入亮/暗两套配色与主题切换。

### 实现逻辑

**1. 修复 `undefined` 标签（枚举 `.value` 误用）**
- 根因：API 返回 `model_dump()` 后，枚举（verdict/flaw_type/error_type）已是纯字符串，但前端多处仍写 `xxx.value` 访问，得到 `undefined`。
- 修复位置（`src/web/static/index.html`）：`goldenBox`(243)、单题回放 `renderSteps`/`detail`(270/277/293/297)、golden 页(307)、interact(340/343/350/358) 共 9 处，去掉 `.value`。
- 保留表单取值的 `.value`（`#iScene`.value 等，非枚举，正确）。

**2. 亮/暗主题切换（仿 Hy_APP 的 teal 青色系）**
- 参照 Hy_APP 机制：`<html data-theme="light|dark">` + 两套 `:root[data-theme=...]` CSS 变量 + `themeBtn` 按钮 + `localStorage` 持久化。
- 主色从蓝色 `#4F6DF5` 改为 Hy_APP 的 **teal 青色**（暗色 `#2dd4bf`，亮色 `#0d9488`）。
- 新增亮色主题整套变量（bg/panel/txt/sub/line/pri/ok/bad/warn 等）。
- 将整页硬编码的深色/蓝色 rgba 全部改为 CSS 变量驱动（`--pri-weak`、`--grad-a/b`、`--sidebar-bg`、`--ok-bg`、`--bad-line`、`--input-bg`、`--td-line`、`--scroll-thumb` 等），保证亮暗切换协调。
- 侧边栏 logo 区新增 `themeBtn`（🌓）切换按钮。
- 新增 `applyTheme`/`toggleTheme` JS，默认 `dark`，持久化到 `localStorage["rex_theme"]`。

### 输入 / 输出
- 输入：无（纯前端 HTML/CSS/JS 改动）
- 输出：`src/web/static/index.html` 主题化改造 + undefined 修复

### 调用文件
- `src/web/static/index.html`（唯一改动文件）

### 验证
- 仪表盘 HTTP 200，HTML 含 `themeBtn`、亮色主题定义，`.value` 误用已清除
- 静态文件实时读取，无需重启后端

---

## 任务 interact-optimize：交互式解题页输入区与渲染优化（计划外，用户临时插入）

**状态**：✅ 已完成

### 背景
用户要求优化交互式解题页：数学/算法输入框分开设计；算法题支持输入输出样例；展示模型代码 + 沙盒结果；支持 Markdown/LaTeX 渲染。

### 目标
1. 数学：题目支持 Markdown + LaTeX（`$$..$$`）实时预览，配标准答案输入
2. 算法：题目描述 + 输入输出样例（多行输入）+ 参考解；样例既拼入 prompt 又作为沙盒测试用例验证代码
3. 结果：Markdown/LaTeX 渲染步骤；算法场景展示模型生成代码 + 测试通过率 + 运行错误

### 实现逻辑

**后端 `src/web/api.py`**
- 新增 `InteractSample`（input/output）模型；`InteractRequest` 增加 `samples` 字段
- `interact`：算法场景把样例既拼入 prompt（`【输入输出样例】`块），又构造成 `TestCase` 填入 `QuestionItem.test_cases`，使沙盒能跑模型代码验证样例

**前端 `src/web/static/index.html`**
- head 引入 KaTeX（css+js）+ marked（CDN）
- 输入区改为数学/算法分开：
  - 数学：题目 textarea + 实时预览（Markdown/LaTeX）+ 标准答案
  - 算法：题目描述 + 样例输入（多组"输入:\n…\n输出:\n…"）+ 样例解析预览 + 参考解
- 新增函数：`renderMath`（marked+KaTeX 渲染）、`parseSamples`（解析样例）、`switchInteractScene`（场景切换）、`previewPrompt`/`previewSamples`（实时预览）
- `interact()` 重写：按场景收集入参（算法解析 samples），结果用 renderMath 渲染步骤，算法场景展示模型代码（`rec.answer.code`）+ 沙盒结果

### 输入 / 输出
- 输入：`POST /api/interact`（scene/prompt/answer/samples/refine）
- 输出：`{mode, eval|refine, elapsed, cost_calls, exec:{test_pass_rate, error}}`（eval 记录含 `answer.code`）

### 调用文件
- 后端：`src/web/api.py`（`InteractSample`/`InteractRequest`/`interact`）
- 前端：`src/web/static/index.html`（交互页 HTML + JS）

### 验证
- `InteractRequest` 正确解析 samples（pydantic 验证通过）
- 仪表盘重启后 HTTP 200，HTML 含 KaTeX/marked CDN、parseSamples、场景切换、样例输入框
- 实际交互需 Hy3 key 调模型（演示时验证）

---

## 任务 frontend-split：前端组件化（index.html 拆分为 styles.css + main.js）

**状态**：✅ 已完成

### 背景
用户希望把单页 index.html 拆成组件/多文件，便于后续所有页面改造（总览/单题回放/golden/抽检等将增强探索性）。项目无构建工具（uvicorn 直接 serve 静态文件），故采用无构建步骤的文件级拆分。

### 目标
将 `src/web/static/index.html` 拆为三个文件：
- `index.html`：HTML 骨架（各 section）+ CDN 引入
- `styles.css`：全部样式（含 Tailwind @import、KaTeX、主题变量）
- `main.js`：全部前端逻辑

### 实现逻辑
1. 用正则精确匹配 `<style>...</style>` 和最后一个内嵌 `<script>...</script>`，提取到 `styles.css` / `main.js`（避免误判 JS 字符串中的 `<script>`）。
2. 重建 `index.html`：`<style>` 块 → `<link rel="stylesheet" href="/static/styles.css">`；内嵌 `<script>` → `<script src="/static/main.js"></script>`。
3. 静态文件实际挂在 `/static` 前缀（api.py 的 `app.mount("/static", StaticFiles(...))`），故使用**绝对路径** `/static/styles.css`、`/static/main.js`。

### 关键踩坑（已在过程中修复）
- **首次拆分脚本用 `rfind("<script>")` 定位错误**，导致 JS 内容混入 HTML，index.html 被破坏。已从 git 恢复并用**正则精确匹配**重拆。
- 静态文件挂在 `/static` 而非根路径，相对路径 `styles.css` 会 404，须用绝对路径。

### 输入 / 输出
- 输入：`src/web/static/index.html`（git 干净版）
- 输出：`styles.css`（8204 字符）、`main.js`（17438 字符）、精简 `index.html`（7541 字符）

### 调用文件
- `src/web/static/index.html`、`styles.css`、`main.js`（三者并列）
- 后端 `src/web/api.py` 挂载 `/static` 提供访问

### 验证
- `/`、`/static/styles.css`、`/static/main.js` 均 HTTP 200
- main.js 含全部关键函数（loadOverview/loadDetail/loadGolden/loadAudit/interact/renderMath/applyTheme 等）+ `loadOverview()` 初始化
- 预览页面功能正常

---

## 任务 record-store：数据孤岛修复 + 集中存储 + 可检索性（计划外，用户主导）

**状态**：✅ 已完成

### 背景
交互式解题的记录此前不落盘（数据孤岛，无法在列表/总览找到）；题目列表无分页/筛选/检索。用户要求：集中处理所有测试结果、默认一个月保存（手动清理）、增加可检索性。

### 目标
1. 集中存储：eval/refine/interact 记录统一管理，带 `created_at` 时间戳 + `source` 来源标注
2. 保留策略：默认一个月，手动清理命令（不自动删）
3. 丰富检索：筛选（场景/难度/判定/来源/关键词/时间）+ 排序 + 分页

### 实现逻辑

**1. 新增 `src/rex/store.py`（RecordStore 记录仓库）**
- `append_eval/append_refine`：统一追加写入（自动补 created_at），按 scene 分文件
- `load_evals/load_refines`：集中读取
- `query_evals`：丰富检索——scene/difficulty/verdict/source/qid/keyword/since/until 筛选 + sort/order 排序 + limit/offset 分页，返回 `(records, total)`
- `expired(days)`：列出超期记录
- `cleanup(days, dry_run)`：手动清理超期记录（默认 dry_run 预览，不自动删）

**2. models.py**：EvalRecord/RefineRecord 加 `source` 字段（默认 "run-eval"）

**3. api.py**
- `interact`：记录落盘到 RecordStore（`source="interactive"`），唯一 id `I{时间戳}`，交互记录进入集中库
- `/api/questions`：改用 `query_evals`，支持筛选/分页/排序，返回 `{items, total, limit, offset}`；每条含 `source`

**4. cli.py**：新增 `cleanup` 命令（`--days 30 --dry-run True` 默认预览，`--dry-run False` 才删）

**5. 前端 main.js**：`loadQuestions` 重构——适配 `{items,total}`，加筛选下拉（场景/难度/判定/来源）+ 关键词搜索 + 分页（上一页/下一页/页码）

### 输入 / 输出
- 输入：`/api/questions?scene=&verdict=&tier=&source=&keyword=&since=&until=&sort=&order=&limit=&offset=`
- 输出：`{items:[...], total, limit, offset}`（每条含 source/created_at）
- 命令：`python -m src.cli cleanup --days 30 [--dry-run False]`

### 调用文件
- 新增：`src/rex/store.py`、`tests/test_store.py`
- 修改：`src/rex/models.py`、`src/web/api.py`、`src/cli.py`、`src/web/static/main.js`

### 验证
- `pytest` 39 项全绿（新增 store 测试：append/query/expired/cleanup）
- `/api/questions?limit=5` 返回分页结构（items=5, total=296）
- 检索正常：verdict=SILENT_FAILURE→3、keyword=A001→6、source=interactive→0、tier=hard→104
- `cleanup --days 30` 预览运行成功（当前无超期记录）
- main.js 语法校验通过

---

## 任务 dashboard-fix2：胶囊圆角回退修复 + 题目列表初始加载提速（计划外）

**状态**：✅ 已完成

### 背景
1. 前端组件化（拆 styles.css/main.js）后，之前做的"克制圆角"调整丢失（因从 git 恢复旧版 index.html），胶囊体风格复现。
2. 题目列表此前不初始加载，需切换页面才显示；用户要求直接显示且要快。

### 目标
1. 恢复克制圆角（无胶囊 99px、无过大 12-16px）
2. 题目列表页面加载即显示，且加载快

### 实现逻辑

**1. 胶囊圆角修复（styles.css）**
因拆分脚本从 git 恢复 index.html 导致之前的圆角调整丢失，重新把以下元素改回克制风格：
- `.tag`/`.round-tab`/`.search`：99px 胶囊 → 6-8px
- `.panel`/`.kpi`：16/14px → 10px
- `.nav-item`/`.finding`：10px → 6px
- `.step-card`：12px → 8px
- `input/textarea`/`.btn`：10px → 8px

**2. 题目列表初始加载 + 提速**
- `main.js` init：`loadOverview()` + `loadQuestions()` 并行，页面加载即显示题目列表（不再依赖切页）
- `RecordStore` 加**内存缓存**（`_eval_cache` + mtime 失效）：`load_evals` 首次读文件后缓存，重复请求走缓存
- `api.py` 用**模块级 STORE 单例**：所有请求（summary/questions/interact）共享缓存，interact append 后失效缓存
- `_load_evals` 改用 `STORE.load_evals()`（走缓存）

### 性能验证
- `load_evals` 首次 21ms，缓存命中 0ms
- `query_evals` 构建 items 1ms，`json.dumps` 100 条 1ms（24KB）
- 实测 `/api/questions` 690ms 为环境 HTTP 固定开销，后端逻辑层极快

### 调用文件
- `src/web/static/styles.css`（圆角）、`src/web/static/main.js`（初始加载）
- `src/rex/store.py`（缓存）、`src/web/api.py`（STORE 单例）

### 验证
- 39 项测试全绿
- 页面加载即显示题目列表
- 胶囊圆角已清除

---

## 前端界面现状总结（供后续二次修改参考）

**状态**：✅ 阶段性完成（界面先保持现状，后续可改）

### 文件结构（组件化后）
```
src/web/static/
├── index.html    # HTML 骨架：5 个 section（评估总览/单题回放/Golden/人工抽检/交互式解题）
├── styles.css    # 全部样式：CSS 变量主题（亮/暗）+ 组件样式
└── main.js       # 全部逻辑：导航/数据加载/交互（无构建工具，原生 JS）
```
- 静态文件由后端 `api.py` 挂载于 `/static/`，index.html 用绝对路径引用 `/static/styles.css`、`/static/main.js`

### 关键特性
| 特性 | 位置 | 说明 |
|---|---|---|
| 亮/暗主题切换 | main.js `applyTheme`/`toggleTheme` | `data-theme` + localStorage("rex_theme")，侧边栏太阳/月亮 SVG 按钮 |
| 圆角风格 | styles.css | 克制 6-10px，无胶囊（99px）；主元素 8px、次级 6px、面板 10px |
| Markdown/LaTeX 渲染 | main.js `renderMath` | marked + KaTeX，`$$...$$` 公式 |
| Markdown 限界 | styles.css `.md-bound` | 所有 Markdown 容器 max-height + 滚动 |
| 题目列表 | main.js `loadQuestions`/`QUIERY_STATE` | 单题回放页内嵌，筛选/搜索/分页 |
| 交互式解题 | main.js `interact` | 数学(LaTeX)/算法(样例)分输入，展示代码+沙盒结果 |

### 单题回放页布局（当前）
- 上：题目列表（横跨全宽，多列 `auto-fill minmax(200px,1fr)`，筛选/搜索/分页）
- 中：题目详情（全宽，`renderMath` 渲染）
- 下：过程回放（全宽，roundTabs 轮次 + 步骤 `renderMath` + findings）
- 完全纵向堆叠，不挤

### 后续二次修改关注点
1. **拆分丢失样式风险**：组件化从 git 恢复时，未提交的编辑会丢。改前先 commit，改后验证 `.fbtn`/`.md-bound`/`renderMath` 调用是否完整。
2. **数据层**：`RecordStore`（src/rex/store.py）集中管理记录，带内存缓存 + 丰富检索 + 手动 cleanup。
3. **交互记录**：`source="interactive"` 落盘，列表可筛选来源。
4. 导航加载：`loadOverview`/`loadQuestions`/`loadGolden`/`loadAudit`/`interact` 各负责一屏。

---

## 任务 sandbox-cpp：沙盒扩展支持多语言（C++ 编译运行）

**状态**：✅ 已完成

### 背景
评测集构建方向（AtCoder + CodeForces 自建）需要运行官方/用户 AC 解作为参考解，而官方解多为 C++。当前沙盒 `run_code` 只支持 Python。

### 目标
扩展沙盒支持 C++（编译 + 运行），为运行 AC 参考解打基础。设计成可配置语言后端，便于后续扩展其它语言。

### 实现逻辑（`src/rex/executor/sandbox.py`）
1. `run_code` 加 `language` 参数（`python`/`cpp`）+ `compile_timeout`
2. **python 路径**：现有逻辑（写 .py，用当前 python 运行）
3. **cpp 路径**（新增 `_run_cpp`）：
   - 写 `_rex_prog.cpp`
   - `g++ -std=c++17 -O2 prog.cpp -o prog.exe`（编译器路径 `REX_GPP` 可覆盖，默认 MSYS2 ucrt64）
   - 编译失败 → 返回编译错误（含 stderr 片段）
   - 编译成功 → 运行 exe（复用 `_run_proc` 子进程方式，stdin/stdout 编码正常）
4. `_run_proc` 抽出公共子进程运行逻辑（python/cpp 共用）

### 验证
- 新增 `tests/test_sandbox.py`（6 项）：python 运行/stdin/超时/语法错误 + cpp 运行(5)/编译错误检测
- g++ 15.2.0 编译的 exe 经 python 子进程运行，stdin/stdout 正常（验证可行）
- 全量 45 项测试通过

### 关键结论
- MSYS2 g++ 编译的 exe 在 PowerShell 直接运行时 stdin 会乱码，但**经 python subprocess 运行正常**——沙盒正是用 subprocess，故可行。

---

<!-- 后续任务按此格式追加 -->

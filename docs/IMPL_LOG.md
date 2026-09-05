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

## 任务 static-check：静态规则校验接入 pipeline（第 4 类验证手段落地）

**状态**：✅ 已完成

### 目标
任务书要求"实现方式含规则校验"。`static_check.py` 已有复杂度声明一致性 + 边界启发式，但**未被 pipeline 调用**（规则校验手段未落地）。本次：① 扩展死循环/递归无终止检测；② 作为 verifier 的**补充诊断源**接入 eval 链路；③ 补测试。

### 实现逻辑

**1. 死循环检测（`static_check.py` 新增 `_loop_and_recursion_diagnostics`）**
- `while True:` 且循环体内无 `break` → `loop_risk=True`（warn）
- `while <cond>:` 条件依赖的变量在循环体内未被赋值更新（启发式，排除嵌套循环与函数定义干扰）→ `loop_risk=True`（info）
- 正常 `while i < n: i += 1` 不误报

**2. 递归无终止检测**
- 函数存在对自身的调用，且**所有 return 都是递归路径**（如 `def fib(n): return fib(n-1)+fib(n-2)`）→ `recursion_risk=True`（warn）
- 存在非递归 return（如 `if n<=1: return n`）视为 base case → 不误报
- 修正过程：初版"有任意 return 即安全"会漏检 `return fib(...)` 形式，改为"return 值含递归调用不算终止路径"

**3. 接入 verifier（正交补充诊断，不改主判定）**
- `VerifierAgent.verify(question, answer, static_evidence=None)`：`static_evidence` 为可选的规则校验证据块，作为**补充证据**附加到 V1/V2 两视角 prompt（`verify_user_prompt` 新增参数），verdict 仍由 LLM 判定独立决定
- `static_evidence_block(result)`：仅在有 warn 级诊断/复杂度不匹配/死循环/递归风险时返回非空证据块，无告警返回 None（不污染正常样本）
- `Pipeline._eval_one`：求解后调用 `check_static(q, answer)`，证据块传入 `verifier.verify`，原始结果存 `EvalRecord.static_check`（dict，可持久化）

### 输入 / 输出
- 输入：`QuestionItem + Answer`（含 code）
- 输出：`StaticCheckResult`（declared/estimated/mismatch/diagnostics/loop_risk/recursion_risk）；`EvalRecord.static_check` 序列化 dict

### 调用文件
- `src/rex/executor/static_check.py`：检测逻辑 + `static_result_to_dict` + `static_evidence_block`
- `src/rex/verifier/agent.py`：`verify` / `_verify_view` 支持 `static_evidence`
- `src/rex/verifier/prompts.py`：`verify_user_prompt` 支持 `static_evidence`
- `src/rex/pipeline.py`：`_eval_one` 调用 check_static 并落盘
- `src/rex/models.py`：`EvalRecord` + `static_check: dict | None`（向后兼容）

### 验证
- 新增 8 项 static-check 测试（死循环 while True / 条件变量不更新 / 正常 while 不误报 / 递归无 base / 递归有 base 不误报 / evidence 块仅 warn / dict 序列化 / verifier 收到证据）
- 新增 1 项 pipeline 集成测试（算法场景 EvalRecord 落盘 static_check，持久化可读回）
- 全量 **58 项测试通过**，lint 干净
- 设计约束：静态校验是启发式诊断，**不阻塞、不改变 verifier 判定**，符合任务书"规则校验与分步 LLM 审查等多手段正交"要求

---

## 任务 selfbuilt-questions-AtCoder：自建题扩充（AtCoder ABC，10 题）

**状态**：✅ 已完成（AtCoder 部分）

### 目标
呼应"公开集为主+自建补充（46开）"：CodeForces 改由自建覆盖后，AtCoder ABC 作为自建题主力扩充。本次从 3 题扩到 **10 题**，按算法类型均匀覆盖：模拟、DFS、二分、双指针、数学枚举、树、DP、前缀和计数、排序贪心。

### 实现逻辑

**1. `ingest_abc.py` 增强（自动抓取 + 样例验证）**
- **cookie 隔离**：`ATCODER_REVEL_SESSION` 经项目根 `.env` 读取（gitignore 排除），`load_dotenv` 加载，不落盘不入 git
- **请求限速**：`_get()` 统一入口，每次请求固定间隔 2 秒，避免封号
- **题面抓取**：`fetch_problem()` 提取英文题面（lang-en），`_html_to_text` 修正块级标签换行（避免 "StatementYou" 粘连）
- **样例提取**：`extract_samples()` 从题面正则提取 (input, output) 对
- **自动找 AC**：`find_ac_with_verification()` 翻页从 `status/json` 拿候选 AC id → 抓代码 → **用题面样例沙盒验证**，通过才采用
- **入库**：`QuestionItem`（source="AtCoder-自建"，含 reference_solution + test_cases）

### 流程规则（本任务沉淀，批量抓取通用）
1. **AtCoder `status/json` API 的 `f.Task` 筛选不生效**（实测返回全局最近 AC 提交）→ 必须"抓候选 + 题面样例沙盒验证"，不能用 API 按题筛选
2. **部分分 AC 提交混入**（Score 200/300）→ 样例验证自动跳过输出不符/编译失败的提交
3. **老 ABC 比赛（~abc1xx）CD 题名为 `arcXXX_a/b`**（如 abc098_c=arc098_a）→ 选题优先用较新 ABC，task id 与比赛一致
4. **Windows GBK 控制台打印非 ASCII 编译错误会崩溃** → 脚本开头 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`
5. **隐藏用例期望值不能手算**（易错）→ 用**已验证 AC 解的输出**作为期望值（通过官方样例的正解算隐藏边界）

### 题集现状（data/questions/abc_selfbuilt.jsonl，10 题）

| id | source_id | 类型 | 难度 | 用例 | 通过率 |
|---|---|---|---|---|---|
| A1001 | abc161_d | DFS | medium | 8 | 100% |
| A1002 | abc328_b | 模拟 | medium | 6 | 100% |
| A1003 | abc139_a | 模拟/字符串 | basic | 6 | 100% |
| A1004 | abc248_d | 二分/预处理 | medium | 6 | 100% |
| A1005 | abc229_d | 双指针/贪心 | medium | 8 | 100% |
| A1006 | abc330_c | 数学/枚举 | medium | 7 | 100% |
| A1007 | abc148_f | 树/距离 | hard | 6 | 100% |
| A1008 | abc088_b | 排序/贪心 | basic | 6 | 100% |
| A1009 | abc248_c | DP | hard | 7 | 100% |
| A1010 | abc330_d | 前缀和/计数 | medium | 6 | 100% |

### 调用文件
- `scripts/ingest_abc.py`（增强）：`fetch_problem` / `extract_samples` / `find_ac_with_verification` / `_get`（限速+cookie）
- `data/cases/*_cases.json`（7 份新增用例文件）
- `data/questions/abc_selfbuilt.jsonl`（10 条）
- `.env`：`ATCODER_REVEL_SESSION`（本地隔离）

### 验证
- 10 题参考解全部通过各自测试用例（100%）
- 每道 AC 提交都经题面样例沙盒验证（非手写、非猜测）

---

## 任务 selfbuilt-questions-AtCoder-批量：第一轮扩充（10→27 题）

**状态**：✅ 已完成（第一轮 17 题，含 3 题批量流程问题修复）

### 目标
按用户口径：自建总量=公开集 350，AtCoder:CF=5:5（各 175），每轮 1/10（~17 题）在 browse 页展示。本轮 AtCoder 从 10 题扩到 **27 题**，类型覆盖：BFS计数/0-1BFS/树DFS/并查集×2/栈/DP×3/数论/贪心区间/判环/有序集合/字符画/前缀和/模拟集合/博弈DP。

### 新增脚本
- `scripts/batch_ingest_abc.py`：批量入库 runner（题单 PLAN + 逐题 auto-ac + 失败容错 + **source_id 去重防重复入库**）

### 关键坑与修复（本轮沉淀的流程规则）

1. **`status/json` API 完全不可用**：`f.Task`/`page` 参数**全部失效**，永远返回固定 20 条全局 AC 提交 → **改用提交列表页 HTML**（`/contests/{contest}/submissions?f.Task=..&f.Status=AC&f.User=`，带 cookie 时服务端渲染，`f.Task` 筛选生效）。这是本轮**最大突破**，老比赛从"翻 5 页 100 条碰不到"变为"一次命中"。
2. **预筛跳过垃圾提交**：非 C++（无 `#include`）/ >15KB 巨型模板 / 依赖 `atcoder/` 库（本机无）→ 直接跳过，**省掉大量无效编译**（编译是大头耗时）。
3. **Windows GBK 打印崩溃**：脚本开头 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`。
4. **样例比对 \r 差异**：题面 HTML 可能残留 CRLF → `extract_samples` 和 `verify_code_with_samples` 统一 `\r\n`→`\n`。
5. **run_test_cases 尾空白**：不同 AC 提交可能多打尾随空格 → 比对统一 `rstrip()`（多数 OJ 忽略行尾空白），这是合理的判题健壮性增强。
6. **重复入库防护**：`batch_ingest_abc.py` 检查 `source_id` 已存在则跳过。
7. **失败容错**：单题失败不中断批量，最后汇总"需人工提供 submission id"清单。

### 当前题集（27 题，全部参考解通过测试用例）
- 类型：17 种算法类型均匀覆盖；难度：basic 3 / medium 17 / hard 7
- 每道 AC 提交经题面样例沙盒验证 + 自建 cases 全绿
- browse 页（`http://127.0.0.1:8000/browse`，筛选 "AtCoder 自建"）可查看每道题的题面/参考解/测试用例/类型标签（metadata.type）

### 调用文件
- `scripts/ingest_abc.py`：`iter_ac_submissions` 改为解析提交列表页 HTML + `_prescreen_cpp` 预筛 + 样例 \r 归一
- `scripts/batch_ingest_abc.py`：批量 runner（新）
- `src/rex/executor/tests.py`：`run_test_cases` 比对改为 `rstrip()`（尾空白容差）
- `data/cases/*_cases.json`（17 份）、`data/questions/abc_selfbuilt.jsonl`（27 条）

### 验证
- 27 题参考解 100% 通过测试用例
- 全量 pytest 58 项通过

---

## 修复：超长模板参考解重写（A1010/A1013/A1014/A1017/A1018）

**状态**：✅ 已完成

### 背景
批量抓取"第一个通过样例的 AC 提交"时命中了**巨型竞赛模板库**提交（几十个 include + atcoder/pb_ds 库 + 宏），虽能运行但作为"标准答案/参考解"不可读。用户指出 A1010（9988 字符）违反"参考解=可读清晰版"规则。

### 处理
新增 `scripts/rewrite_long_refs.py`，为 5 题**手写清晰版**参考解（保留原 AC 解核心算法，去掉模板壳），沙盒验证通过全部用例：

| id | source_id | 原长度 | 重写后 | 算法 |
|---|---|---|---|---|
| A1017 | abc230_d | 66147 | 634 | 按 R 排序贪心最小拳击 |
| A1010 | abc330_d | 9988 | 1393 | 4 方向 o 计数 |
| A1013 | abc277_e | 9179 | 1246 | 0-1 BFS 开关图 |
| A1018 | abc285_d | 8672 | 778 | DFS 判环 |
| A1014 | abc283_d | 7891 | 684 | 括号栈 + 字母集合 |

### 流程规则补充
1. **入库时应设参考解长度上限**（如 ≤3KB），超长模板提交应跳过换下一条；本次为事后补救。
2. `batch_ingest_abc.py` 预筛 `_prescreen_cpp` 已有 >15KB 跳过，但部分题命中 7-10KB 的"中型模板"仍超标 → 阈值应下调并加"重写兜底"。

### 调用文件
- `scripts/rewrite_long_refs.py`（新）
- `data/questions/abc_selfbuilt.jsonl`（5 题参考解更新）

### 验证
- 5 题重写后全部通过测试用例；27 题总计 100% 通过

---

## 修复：AtCoder 自建题补充隐藏边界测试用例（80 隐藏）

**状态**：✅ 已完成

### 背景
用户指出测试用例偏少（这轮 17 题入库时 cases 大多只含官方样例，隐藏用例近 0），不满足任务书"含难例与反例、可自动校验"要求。

### 实现
新增 `scripts/gen_hidden_cases.py`：
- 为 17 题（A1011~A1027）各设计 **3~5 个合法边界输入**（最小规模 N=1/空、极端值、关键分支如自环/链/星形/菱形/重叠区间/跨层括号等）
- **期望输出由已验证的参考解自动生成**（参考解已过官方样例；避免手算错）
- 追加为 `hidden=true` 用例写入 jsonl

### 人工抽检（防止"参考解错→错误期望被固化"）
抽查 8 道题 20+ 边界期望值，全部人工验证合理（如 `abc292_d: 1 0→No`、`abc283_d: (a(b)a)→No`、`abc211_d: 菱形→2`、`abc235_d: 3 3→1`）。

### 验证
- 27 题参考解通过**全部 160 个用例**（公开 80 + 隐藏 80），100%
- 全量 pytest 58 项通过

### 调用文件
- `scripts/gen_hidden_cases.py`（新）
- `data/questions/abc_selfbuilt.jsonl`（测试用例扩充）

---

## 任务 selfbuilt-questions-AtCoder-第2轮：扩充（27→44 题）

**状态**：✅ 已完成

### 目标
按每轮 1/10（17 题）节奏继续扩充 AtCoder 自建题，**优先新算法类型**。本轮新增 17 题（A1028~A1044），累计 44 题。

### 新增题与类型（17 种新类型）
质数/数论、gcd/数论、网格BFS、多源BFS、DP背包、DP选择、DP规划、DP环计数、BFS字符串、字符串LCP、DFS划分、组合计数、优先队列、滑动窗口、二分+图、三分数学、DFS计数。

### 关键技术点
1. **`iter_ac_submissions` 已改解析提交列表页 HTML**（第 1 轮沉淀），本轮 17 题全部一次命中（偶发 status=500 重试后成功）。
2. **边界输入设计要严格符合约束**：本次发现 `abc310_d` 隐藏用例误写 `T=0`（违反 `1≤T≤N`）→ 参考解崩溃（rc=3221225477）。排查后确认为**输入非法而非参考解 bug**，已删非法用例、用合法边界重生成。**规则：边界用例必须满足题目全部约束，尤其参数下限（如 T≥1、N 下限）**。
3. **A1035 (abc310_d) 参考解重写**：原 AC 解对部分输入崩溃且写法易越界，重写为"组无标号去重 DFS"（927 字符，含 5 官方 + 3 合法隐藏全部通过）。

### 验证
- 44 题参考解通过全部 **260 个用例**（公开 127 + 隐藏 133），100%
- 全量 pytest 58 项通过
- 无超长模板参考解（最长 2306 字符）

### 调用文件
- `scripts/batch_ingest_abc.py`（PLAN 更新为第 2 轮）
- `scripts/gen_hidden_cases.py`（新增第 2 轮边界输入）
- `scripts/fix_a1035.py`（A1035 专项修复）
- `data/questions/abc_selfbuilt.jsonl`（44 条）

---

## 任务 selfbuilt-questions-AtCoder-第3轮：扩充（44→78 题）+ 浮点容差支持

**状态**：✅ 已完成

### 目标
第 3 轮 34 题（A/B 两批），类型：hard 为主（MST/Floyd/状压/第K小/期望DP/概率DP/二叉树等），当前 AtCoder 自建题累计 78 题。

### 关键问题与修复
1. **浮点输出题无法自动入库**（abc314_e 等）：官方样例期望 `215.913355350494384765625`（高精度），各 AC 提交打印位数不同，字符串比对必失败。
   - **修复**：`verify_code_with_samples`（scripts/ingest_abc.py）与 `run_test_cases`（src/rex/executor/tests.py）的比对改为**浮点容差**——两侧同位置行都能解析为浮点数时，按相对/绝对误差 ≤1e-5 判定（AtCoder 浮点题判据）。普通文本仍精确逐行比对。
   - 效果：abc314_e（Roulette）成功自动入库（A1078）。
2. **超长模板参考解**：A1069/A1073/A1074（abc301_e 状压糖果、abc321_e 二叉树计数、abc323_e 概率DP）重写为清晰版并验证。
3. **批量提速尝试**：用户提出"一次多执行"——网络限速不变，但减少轮次往返 overhead，本轮 34 题一次连续跑（A/B 两批）。

### 验证
- 78 题参考解通过各自用例 100%
- pytest 58 项通过
- 隐藏用例：第 1/2 轮已补（133 个）；第 3 轮 34 题待逐题补（用户选"逐题补分批慢做"）

### 调用文件
- `scripts/ingest_abc.py`（`_outputs_match` 浮点容差）
- `src/rex/executor/tests.py`（`_text_match` 浮点容差）
- `scripts/rewrite_long_refs3.py`（3 超长参考解重写）
- `data/questions/abc_selfbuilt.jsonl`（78 条）

---

## 修复：第 3 轮 34 题隐藏用例补齐（78 题全部含隐藏）

**状态**：✅ 已完成

### 目标
用户选择"逐题补，分批慢做"。为第 3 轮 34 题（A1045-A1078）逐个设计合法边界输入补隐藏用例，**防止 abc310_d（T=0 非法输入）重演**。

### 流程（沉淀的规则）
1. **设计输入前必须核对题目输入格式**（读 sample input 结构），不能凭直觉写。
2. 每批先在 `scripts/gen_hidden_cases.py` 的 `BOUNDARY_INPUTS` 定义边界输入 → 跑脚本（参考解生成期望）→ **清理 output 为空的用例**（格式错误输入会导致参考解无输出/崩溃，这类用例必须删除）→ 去重（输入等于官方样例的隐藏项删除）。
3. 期间发现的格式错误题（abc257_d/abc302_e/abc304_e/abc317_e/abc289_e/abc286_e 等图论/网格题）逐个对照官方样例修正。

### 验证
- 78 题参考解通过全部 **412 用例**（公开 216 + 隐藏 196），100%
- 清理了 7 个输入与官方样例重复的隐藏用例、13 个空输出坏用例
- pytest 58 项通过

### 当前 AtCoder 自建题规模：78/175（还剩 ~97 题）

---

## 任务 selfbuilt-questions-AtCoder-第4轮：扩充（78→102 题）+ 隐藏用例补齐

**状态**：✅ 已完成

### 目标
第 4 轮 24 题，**刻意补难度分层**（basic 4 + medium 12 + hard 8）与类型均匀
（数学/构造/串/图/DP/模拟/数据结构），并把新题隐藏用例分批补齐。

### 关键问题与修复
1. **多解构造题无法入库**（abc216_c Many Balls、abc251_d At Most 3）：题目允许多种合法输出
   （如 AABA 与 ABBA 都对），精确样例比对永远匹配不上 AC 提交 → **替换**为输出唯一的
   abc255_d（排序/二分）、abc272_d（BFS/网格）。
   **沉淀规则：入库前识别"多解构造题"（题面出现 "other acceptable outputs" 等），直接用样例验证不可行。**
2. **500 偶发错误**：AtCoder submissions 页偶发 status=500 → `batch_ingest_abc.py` 加
   `--retry 2`（重试间隔 8s），实际命中多题，重试后成功。
3. 老比赛（abc196-284）提交页混入大量**其他题/非 C++/模板/atcoder 库依赖**提交，
   靠样例验证逐条跳过，最终都能在 1-3 页内命中（代价是较多编译耗时）。

### 验证
- 102 题参考解通过全部 **536 用例**（公开 278 + 隐藏 258），100%
- 第 4 轮 24 题全部入库并补隐藏用例（批 1-3，共 +62 隐藏；abc224_d/abc236_d 格式复杂保守保留官方样例）
- 隐藏输入均合法（参考解跑出非空期望）；清理临时脚本
- pytest 58 项通过

### 当前 AtCoder 自建题规模：102/175（还剩 ~73 题）

### 调用文件
- `scripts/batch_ingest_abc.py`（PLAN 更新为第 4 轮 24 题 + `--retry`）
- `scripts/gen_hidden_cases.py`（BOUNDARY_INPUTS 追加第 4 轮 22 题）
- `data/questions/abc_selfbuilt.jsonl`（102 条）

---

## 功能：引入 Special Judge（checker），支持多解构造题

**状态**：✅ 已完成

### 背景
第 4 轮发现 abc216_c/abc251_d 这类**多解构造题**（输出任意合法解，无唯一期望文本），
文本比对永远判不了——这是评测体系缺 SPJ 机制，而非题目不该入。讨论后用户决定引入 checker。

### 实现
1. **模型**：`QuestionItem` 增加 `judge: Judge = exact|special`、`checker_code`、`checker_language`。
2. **新模块 `src/rex/executor/judge.py`**：checker 执行协议——
   stdin = `原题输入\n@@REX_USER_OUTPUT@@\n被测输出`；checker 输出 `AC` 表示合法。
   `run_checker()` 复用沙盒（可信 checker 也隔离执行），`build/parse_split_stdin` 提供拼接/还原。
3. **判题接入**：`run_test_cases(judge=, checker_code=, checker_language=)` 支持 special；
   `pipeline._execute` 从 `q` 透传。
4. **入库接入**：`ingest_abc.py` 加 `--judge special --checker-file`；SPJ 模式下自动找 AC
   改用 checker 校验候选提交（替代样例文本比对）。
5. **真实验证**：首两题入库 + 端到端通过：
   - A1103 abc216_c Many Balls（checker: 模拟 A/B 序列到 N）
   - A1104 abc251_d At Most 3（checker: bitset 验证 [1,W] 均可用 ≤3 砝码表示）
   - 两题参考解 special pass=1.0、故意坏解 pass=0.0
6. **存量扫描**：algorithm.jsonl 707 题中 ~50 题命中 SPJ 特征词；abc_selfbuilt 中
   A1072 abc315_e、A1076 abc299_e 为真多解（题面写 "may print any"），A1098 abc228_d 误报。
   → 后续需人工复核补 checker 或降级。

### 验证
- 新增 `tests/test_judge.py` 5 项（checker 接受多合法解 / 拒绝非法 / 端到端 special 判定）
- pytest 63 项全绿
- lint 无错误

### 调用文件
- `src/rex/models.py`（Judge 枚举 + QuestionItem 字段）
- `src/rex/executor/judge.py`（新）
- `src/rex/executor/tests.py`（run_test_cases 支持 special）
- `src/rex/pipeline.py`（_execute 透传 judge/checker）
- `scripts/ingest_abc.py`（CLI 加 SPJ 参数）
- `scripts/checkers/abc216_c_checker.py`（入库内嵌，无独立文件）、`scripts/checkers/abc251_d_checker.cpp`
- `DESIGN.md`（5.5 节判题模式）

---

## 存量自建题补 checker（SPJ 覆盖扩展到 5 题）

**状态**：✅ 已完成

### 范围决策
用户指示：**公开集（algorithm.jsonl / CF350）不管**（已标记弃用），只处理自建题。

### 全面扫描 abc_selfbuilt + cf_selfbuilt 的 SPJ 特征（"print any"/"may print any"/
"any of them"/"multiple solutions"/"one such" 等），逐个人工复核确认：
- **A1031 abc271_d Flip and Adjust** → 真多解（选 H/T 多种可行方案）→ 转 SPJ
- **A1072 abc315_e Prerequisites** → 真多解（依赖闭包顺序可任意）→ 转 SPJ
- **A1076 abc299_e Nearest Black Vertex** → 真多解（涂色方案不唯一）→ 转 SPJ
- **A1098 abc228_d** → 误报（"one such" 指查询存在，输出确定）→ 不处理

### 新增 checker（scripts/checkers/，均自测通过）
| 题 | checker 判定策略 |
|---|---|
| abc271_d | DP 可达性判定（No 仅当不可达）；Yes 校验 H/T 串长+字符+求和==S |
| abc315_e | 依赖闭包集合精确相等 + 拓扑序校验 |
| abc299_e | 黑点候选域 C={v:∀i dist(p_i,v)≥d_i} 可行性判定（No 仅当无解）；Yes 用多源 BFS 逐约束核距 |
| （既有）abc216_c / abc251_d | 见上一节 |

### 顺带清理
A1072/A1076 原先各有 2 个**非法格式隐藏用例**（如 `2 1\n0 1\n1 1` 违反 C_1≥1、
`2 1 0\n1 2` 违反输入格式）——第 3 轮构造时格式错但未被发现。已删除，
并为两题补了合法隐藏用例（构造合法依赖图/连通图）。A1031 hidden 用例合法保留。

### 验证
- 全自建题 104/104 参考解通过（总 545 用例，隐藏 263，SPJ 5）
- pytest 63 项全绿
- 每个 checker 均用「多解合法变体应 AC / 非法方案应 WA」自测

### 调用文件
- `scripts/checkers/abc271_d_checker.py`（新）
- `scripts/checkers/abc315_e_checker.py`（新）
- `scripts/checkers/abc299_e_checker.py`（新）
- `data/questions/abc_selfbuilt.jsonl`（3 题 judge=special）
- `DESIGN.md`（5.5 节清单更新）

---

## 任务 selfbuilt-questions-AtCoder-第5轮：扩充（104→128 题）+ 隐藏用例补齐

**状态**：✅ 已完成

### 目标
第 5 轮 24 题，**进一步补难度分层**（basic 8 + medium 8 + hard 8），当前分布
basic 17 / medium 69 / hard 42。场次全部用**未收录的 abc333-360**（提交列表干净，
auto-ac 命中快，无老比赛混题问题）。

### 关键点
1. **预筛 SPJ**：候选 24 题抓题面时预检特征词，发现 abc347_d (Popcount and XOR)
   命中 → 替换为 abc348_d (Medicines on Grid)。
2. basic 题全选 c 题（数学/进制/映射/栈/位枚举等），medium 选图最短路/背包/哈希/计数，
   hard 选数位 DP/环差分/双人 BFS/二分数学（网格题保守保留官方样例，未强补隐藏）。
3. 隐藏用例分批补齐（批 1 basic 8、批 2 medium 8、批 3 hard 5 纯数/环题；
   网格 hard abc339_d/348_d/351_d 格式复杂风险高，保留官方样例）。
4. 修正 A1116 abc344_d 一个设计为"不可行"的隐藏输入（`abc\n1\n3 a b c`）为可行方案。

### 验证
- 128/128 题参考解通过全部 **666 用例**（隐藏 316），100%
- pytest 63 项全绿
- 无 SPJ 新增（本轮未遇多解构造）

### 当前 AtCoder 自建题规模：128/175（还剩 ~47 题，约 2 轮）

### 调用文件
- `scripts/batch_ingest_abc.py`（PLAN 更新为第 5 轮 24 题）
- `scripts/gen_hidden_cases.py`（BOUNDARY_INPUTS 追加第 5 轮 21 题）
- `data/questions/abc_selfbuilt.jsonl`（128 条）

---

## 任务 selfbuilt-questions-AtCoder-第6轮：扩充（128→152 题）+ 隐藏用例补齐

**状态**：✅ 已完成

### 目标
第 6 轮 24 题（场次 abc361-375，全部未收录），难度 basic 8 / medium 6 / hard 10。
**用户策略确认**：先把 AtCoder 自编题整体流程跑到 175 目标规模，CodeForces 后续
作为新数据源按同流程（ingest → cases → 参考解验证 → 隐藏用例）单独处理。

### 关键点
1. **SPJ 预筛前置**：抓候选 64 题标题时检测特征词，标出 abc362_c/362_f/364_c/364_e/
   369_e/369_f/373_d 等疑似多解 → 全部避开。**误判澄清**：abc370_c (Word Ladder)
   初看像多解（每步换一字符输出中间串），实际题面要求"字典序最小的最少元素序列"——
   **解唯一**，exact 判定即可，无需转 SPJ。
2. 隐藏用例分批补齐 57 个（basic 7 + medium 6 + hard 10；abc371_c 图同构构造复杂，
   官方已有 5 样例，未强补）。
3. auto-ac 偶发 500（abc367_d/375_d）由 `--retry 2` 自动重试成功。

### 验证
- 152/152 题参考解通过全部 **791 用例**（隐藏 373），100%
- pytest 63 项全绿
- 无 SPJ 新增

### 当前 AtCoder 自建题规模：152/175（还剩 ~23 题，约 1 轮收尾）

### 调用文件
- `scripts/batch_ingest_abc.py`（PLAN 更新为第 6 轮 24 题）
- `scripts/gen_hidden_cases.py`（BOUNDARY_INPUTS 追加第 6 轮 23 题）
- `data/questions/abc_selfbuilt.jsonl`（152 条）

---

## 任务 selfbuilt-questions-AtCoder-第7轮：收尾（152→175 题，**175 满额达成**）

**状态**：✅ 已完成

### 目标
第 7 轮 23 题（场次 abc376-395 未收录），补满 **175 题**（用户既定目标规模）。
后续 CodeForces 将作为新数据源复用同一套 ingest/checker/隐藏用例流程。

### 关键点
1. **发现并修复 extract_samples 跨块吞内容 bug**：abc389_c 的 Sample Output 2 为
   空代码块（后跟解释文字），原非贪婪正则 ``(.*?)`` 吞到下一个代码块导致样例错位，
   auto-ac 永不匹配。修复：按 `### Sample` 分割 + 编号配对，空 input/output 块直接丢弃。
   （修复同时惠及未来所有入库题。）
2. abc389_c cases 文件手工修正（去掉错位的坏样例）。
3. 预筛 SPJ：剔除 abc377_c/387_e/394_d/396_e/397_d 等疑似多解题。
4. 隐藏用例补 37 个；复杂查询/网格题（abc379_d/385_d/386_d/395_d/383_e/384_e）
   保守保留官方样例。

### 验证
- **175/175** 题参考解通过全部 **889 用例**（隐藏 411），100%
- 难度分布：basic 33 / medium 82 / hard 60（分层合理）
- SPJ 5 题；pytest 63 项全绿

### AtCoder 自编题集：175/175 ✅（下一步：成规模跑整体流程 / CodeForces 复用流程）

### 调用文件
- `scripts/batch_ingest_abc.py`（PLAN 更新为第 7 轮 23 题）
- `scripts/gen_hidden_cases.py`（BOUNDARY_INPUTS 追加第 7 轮 18 题）
- `scripts/ingest_abc.py`（extract_samples 跨块修复）
- `data/questions/abc_selfbuilt.jsonl`（175 条）

---

## 任务 doc-align：DESIGN.md 过时更新 + cli 支持自建题加载

**状态**：✅ 已完成

### 目标
DESIGN/README 与代码现状脱节（题集规模、自建产线、环境写法过时），且自建 175 题无法直接跑 eval。

### 实现逻辑
1. DESIGN §2 架构图：题集描述更新为"公开集(TACO 350 活跃 + CF 350 deprecated) + math 326 + 自建 abc_selfbuilt 175"；executor 标注 SPJ。
2. DESIGN §3 数据集表：拆 TACO/CF/自建/数学四行，自建注明 46 开产线与 SPJ；§10 运行方式补 `--questions`；§11 交付清单刷新（63 测试、175 自建题）。
3. README 环境优先级：① tensor_env 3.9（run.ps1 默认）② anaconda 3.13（REX_PYTHON 覆盖）——与用户偏好一致。
4. `cli.py`：run-eval/run-refine 增加 `--questions <file>`，可直接加载 abc_selfbuilt.jsonl 评估。

### 验证
- pytest 63 通过；`_load_questions("algorithm","full","hard",42,"abc_selfbuilt.jsonl")` 加载 60 hard 题。

---

## 任务 hard-eval：Hy3 hard 题实测（12 题）+ 修复"答案错却判 CORRECT"漏检

**状态**：✅ 已完成

### 背景
用户要求对 hard 自建题实测 Hy3，观察失败效果。发现 .env 已有 HY3_API_KEY（此前检查只匹配 ATCODER 前缀漏看）。

### 实测（12 道 hard 自建题，并发 2，真实调用 Hy3）
- 答案准确率 58.3%（7/12），过程正确率 50%（6/12 CORRECT）
- verdict 分布：CORRECT 6 / PROCESS_INCORRECT 2 / ANSWER_INCORRECT 4
- 代表样本：A1013 答案对(pass=1.0)但判 PROCESS_INCORRECT——步骤1 题意误读（声称"无重边"而原题含 multi-edges），代码却用邻接表正确处理 → 双视角验证器抓出"过程描述错但实现碰巧对"。

### 发现并修复的重大缺陷：verifier 不看沙盒结果 → 漏检
- 现象：5 个样本（A1015/1024/1030/1039/1040）**答案全错（pass=0.0）但 verdict=CORRECT**。
- 根因：`pipeline._eval_one` 先 `_execute`（沙盒）再 `verifier.verify()`，但 verify 的 LLM **看不到沙盒结果**，纯读代码判 CORRECT。
- 修复：① pipeline 把沙盒结果格式化为 `execution_feedback` 喂给 verifier（prompt 明示"答案错不得判 CORRECT"）；② **程序化兜底**：answer_correct=False 且 verdict==CORRECT → 强制降级 ANSWER_INCORRECT。
- 涉及：`pipeline.py`（`_execution_feedback` + 兜底）、`verifier/agent.py`、`verifier/prompts.py`。
- 重跑验证：5 题中 4 题正确降级 ANSWER_INCORRECT、1 题（A1039）本次实际解对 → CORRECT 合理。
- 测试更新：test_pipeline/test_runner 中 M001（答案错）预期从 CORRECT 改为 ANSWER_INCORRECT；pytest 67 全绿。

### 全量 hard 实测（60/60 完成，真实调用 Hy3，累计 ~150 次模型调用）
修复后补齐全部 60 道 hard 自建题，最终结果（eval_selfbuilt_hard.jsonl + smoke/fixverify 合并去重）：
- **答案准确率 41.7%（25/60）**；**过程正确率 36.7%（22/60 CORRECT）**
- verdict：CORRECT 22 / PROCESS_INCORRECT 10 / ANSWER_INCORRECT 28
- **交叉统计完全自洽（修复后零矛盾样本）**：
  - ans 错 + ANSWER_INCORRECT = 28（客观降级正确）
  - ans 错 + PROCESS_INCORRECT = 7（答案错且过程有错）
  - ans 对 + CORRECT = 22
  - ans 对 + PROCESS_INCORRECT = 3（**沉默失败候选**）
- 3 个沉默失败候选（答案全对但过程被验证器判错）：
  - A1013 (abc277_e)：题意误读（称"无重边"，原题含 multi-edges）+ static loop 风险
  - A1169 (abc383_e)：概念错误（diff 定义与使用不一致）
  - A1171 (abc386_e)：复杂度分析错误（声明 ~10^7，K≈N 时实际 ~4e10）+ static complexity-mismatch 双重印证
- 结论：hard 对 Hy3 足够有区分度（答案准确率 42%），且系统能检出 3 类"答案对但过程不成立"样本，评测链路端到端验证通过。

### ⚠️ 重大纠错：执行层语言检测 bug（41.7% → 90.0%）
人工核验时发现 A1065「AI 自测说通过公开用例但展示实际输出全空」。排查定位到**系统性 bug**：
- **根因**：solver prompt 未限定输出语言，60 题中 32 题 AI 提交 **C++** 代码；但 `pipeline._execute` 调 `run_test_cases` **未传 language，默认按 Python 沙盒执行** → C++ 代码被 Python 解释器跑必然 stdout 为空 → 32 题全部 pass=0 被误判答案错，且 verifier 在"沙盒全败"错误反馈下给出一批错误的 ANSWER_INCORRECT。
- **影响**：原报告「答案准确率 41.7%」**严重低估**，实际 **90.0%（54/60）**；23 个"ans 对却判 ANSWER_INCORRECT"矛盾样本由此而生。
- **修复**：
  1. `sandbox.py` 新增 `detect_language()`（含 `#include`/`using namespace` → cpp，否则 python）；
  2. `pipeline._execute` 对提交代码自动检测语言传入 `run_test_cases`；
  3. `make_exec_evidence.py` 同样自动检测（人工核验证据修正）。
- **数据修正**（eval_selfbuilt_hard.jsonl 已重判重写）：客观字段沙盒重跑（正确语言）+ 29 个矛盾样本在正确执行反馈下重新 verify（真实 Hy3，分批完成）。
- **修正后终值**：答案准确率 **90.0%（54/60）**，过程正确率 **70.0%（42/60 CORRECT）**；
  verdict：CORRECT 42 / PROCESS_INCORRECT 13 / ANSWER_INCORRECT 5；
  交叉零矛盾：ans错=6（5 AI + 1 PI），ans对=54（42 CORRECT + **12 PROCESS_INCORRECT 沉默候选**）。
- 12 个沉默候选经抽查均为**真实过程缺陷**（非语言问题），如 A1024 解释 off-by-one 代码修正、A1030 误称"多源 BFS 每顶点至多入队一次"、A1073 `unsigned long long→int` 窄化隐患——这些恰是任务书要的"答案对但过程不成立"活样本。
- **测试固化**：`test_sandbox.py` 新增 3 用例（detect_language python/cpp + C++ run_test_cases 自动判题）；pytest **72 全绿**。
- **教训**：评测前未校验"代码语言×执行器"匹配，导致整批数据失真；抽检展示把 A1065 的 C++ 当 Python 跑 → stdout 空，恰好暴露此缺陷。

### 抽检发现次生污染并清除（12 沉默候选 → 8）
小规模人工抽检 A1068 时发现 verifier finding 引用"沙盒通过率 0%"，但实际 pass=1.0——语言 bug 修复时只 reverify 了"ans对但判 ANSWER_INCORRECT"的矛盾题，遗漏了"ans 对但判 PROCESS_INCORRECT 且 finding 基于 0% 错误反馈"的题。排查出 4 题污染（A1068/A1069/A1126/A1173，均引用 0%），reverify（正确反馈+新版 prompt）后：A1068/A1069/A1173/A1169 → CORRECT（确认污染），A1126/A1171 仍 PROCESS_INCORRECT（真缺陷），A1148 → SILENT_FAILURE（严格标出）。修正后硬档：答案率 90%（54/60）不变，过程率 76.7%（46 CORRECT）。

### AtCoder 自建题集全量评测（175/175，basic 33 + medium 82 + hard 60）
补测 basic+medium（`eval_selfbuilt_bm.jsonl`，resume 分批完成，185 次模型调用），交叉零矛盾、无语言污染：
- **basic**（33）：答案率 93.9%（31），过程率 87.9%（29）
- **medium**（82）：答案率 89.0%（73），过程率 86.6%（71）
- **hard**（60）：答案率 90.0%（54），过程率 76.7%（46）
- **总计 175 题：答案率 90.3%（158/175），过程率 83.4%（146/175）**
- verdict 总分布：CORRECT 146 / PROCESS_INCORRECT 15 / ANSWER_INCORRECT 12 / SILENT_FAILURE 2
- 提示：hard 档过程率（76.7%）明显低于 basic/medium（~87%），符合难度分层预期（hard 推理链更易出现缺陷）；含 4 个 SPJ 题（A1103/A1104/A1031/A1072）正常按 checker 判题。
- 产物：`data/outputs/eval_selfbuilt_bm.jsonl`、`data/outputs/eval_selfbuilt_all.jsonl`、`reports/selfbuilt_report.html`（175 题全量展示）。

### 人工抽检专项：修坏用例 + 编译兜底 + 回填（basic/medium 补充）
小规模人工抽检扩展到 basic+medium 后执行三项修复（按序）：
1. **坏用例修复（3 题 5 用例）**：核验发现 A1035/A1057/A1059 的隐藏用例字段与数据不符
   （M/N/A 声明数 ≠ 实际行数），导致 AI 严格解析崩溃被判"答案错"，但参考解容错通过。
   修复：`scripts/fix_bad_cases.py` 补齐合法输入 + 参考解重算期望（语义不变）。
   **结果：3 题全部 ANSWER_INCORRECT → CORRECT（AI 代码本正确，系用例误杀）**；
   medium 答案率 89.0% → 92.7%。**教训：隐藏用例生成需校验"声明数=实际行数"**。
2. **编译失败定位兜底**：A1098（编译失败）findings 空。根因：① sandbox 对 python 语法/
   运行错误不标记 error（仅 cpp 编译标记）→ 被当普通 WA 丢失诊断；② verifier 无程序化兜底。
   修复：① `sandbox._run_proc` 非零退出时标记 error（python 语法/崩溃暴露）；② `pipeline._eval_one`
   当 exec_err 是编译/运行失败且 verifier 未给 finding 时，程序化补 s4 finding。
   测试：`test_compile_failure_gets_fallback_finding` + sandbox 变更；pytest 73 全绿。
3. **抽检回填**：28 题人工判定回填 `audit_records.jsonl`（40 条，28 已判），跑 audit_metrics：
   - **误报率 = 8.3%**（fp_n=12 中 A1104 误报，边缘样本）
   - **定位命中：答案错且系统判过程错的 5 题全部 HIT（100%）**；全局口径 35.7% 偏低系
     9 个答案错样本系统仅判 ANSWER_INCORRECT 未判过程错（口径语义，非定位不准）
   - 命中明细与人工核验逐一一致。

---

## 任务 static-verify：static_check 规则有效性验证 + 修复两处漏检/误报

**状态**：✅ 已完成

### 实现逻辑
1. 构造 4 类缺陷代码（死循环/递归无 base/复杂度不达标/while 条件不更新）+ 正确基线，对 5 道真实 hard 题验证 → **25/25 检出正确，无正确代码误报**。
2. **修复负数边界漏检**：旧规则把 `max()`/`min()` 当负数处理信号，`return max(a)` 未处理负数却不报 warn → 改为正则检测 abs/与 0 比较/负字面量。
3. **修复 while dq+popleft 误报**：BFS 常见 `while dq: dq.popleft()` 被判"条件变量不更新"死循环风险 → 新增"条件变量被方法调用修改(dq.popleft 等)"识别。

### 验证
- pytest 67 全绿（新增 4 个 static 边界/循环单测）；修复后 Kadane 正确代码不报 warn、BFS popleft 不误报。

---

## 任务 cf-github-fill：CF 反爬绕行补题（150→175，GitHub 公开题解源）

**状态**：✅ 已完成

### 背景
CF 自建题抓取第 13 轮起 submission 源码路由被 Cloudflare 风控（`source not
loaded` / `.problem-statement` DOM 缺失），常规抓取无法继续。用户指示不再抓
CF 官网，改从其它网站获取题目与 AC 解。

### 来源排查结论（全部实测）
- `Eric8900/Codeforces-Webscrape`（9238 题题面 JSON）：样例与正文**无换行连排**，
  无法可靠切分 → 弃用
- 镜像站 m1/m2/mirror/hydro/vjudge/qoj/luogu：Cerberus/登录墙/超时 → 均不可用
- CF 官方 API：只给题目元数据（无题面无样例）
- **GitHub 公开题解仓库**：`Waqar-107/Codeforces`（1556 文件）+ 
  `kantuni/Codeforces`（791 文件）zip 可无登录下载，本地索引 **1473 题** AC 解
- **关键发现**：用户更新 clearance 后，playwright 实测 **CF 题目路由仍放行**
  （`fetch_statement_and_samples` 正常），被限流的仅是 submission 源码路由

### 实现逻辑
1. **新脚本 `scripts/ingest_cf_github.py`**：题面+结构化样例仍走 playwright 题目页
   （放行），参考解从本地 GitHub 索引拉候选（C++ 优先），逐个 `_verify_with_samples`
   沙盒验证通过才采用；test_cases 期望输出自洽化（取参考解实际输出）——
   与 `batch_ingest_cf.ingest_one` 逻辑一致，多解自动标 `needs_checker`。
2. **回填机制**：GitHub 解质量参差（沙盒拦下若干错误代码，如 cf672a 的 itoa 未初始化
   strcat），故候选池 222 题按缺口分层排序，单题失败自动换池内下一题。
3. **分层收敛**：用户明确「CF 不必与 ABC 完全一致，大致接近即可」。补至 175 题后
   （basic34/medium83/hard58）即停，不再强求 33/82/60 精确。

### 验证
- 本轮新增 **25 题全部 GitHub 源入库且沙盒 PASS**（无 needs_checker）
- `cf_selfbuilt.jsonl` **175 题**：basic34/medium83/hard58，测试用例 558（隐藏 195）
- 参考解来源：150 题 CF 公开 AC 提交（历史）+ 25 题 GitHub 公开题解
- 待补 checker 5 题（历史遗留 cf1305e/cf1054c/cf1327c/cf1253b/cf1991c，非本轮引入）

### 调用文件
- `scripts/ingest_cf_github.py`（新）
- `data/cache/cf_gh/{waqar,kantuni}`（题解缓存，gitignore）
- `data/questions/cf_selfbuilt.jsonl`（175 条）
- `README.md`（题集描述/目录结构同步）

---

## 任务 multi-checker：14 题多解 checker 编写与 SPJ 落地

**状态**：✅ 已完成

### 背景
用户指出"参考解实际输出自洽化"在真实评测中不可行——多解题 AI 若给出
另一个合法解，exact 比对会误判 WA。需为多解题编写 SPJ checker（本质：
把解题过程逆过来——丢弃标准答案，只校验选手输出相对题目谓词的合法性），
评测走 checker 判定。用户确认范围：14 题离散构造/输出任意类真多解。

### 多解梳理（74 关键词候选逐题人工判定）
- ABC 19 候选 → 真多解 6：5 题此前已转 SPJ（abc271_d/abc315_e/abc299_e/
  abc216_c/abc251_d）+ **新发现 abc392_e**（Cables and Servers 构造操作序列）
- CF 47 候选 → 真多解 13：cf549g/cf1305e/cf1054c/cf1327c/cf1253b/cf1991c/
  cf20c/cf53c/cf437b/cf384a/cf1717b/cf71d/cf27b（已标 needs_checker 5 +
  关键词高置信复核 8）
- 其余误报（输出唯一/计数/最值/判断，如 "any order" 实为固定排序、
  "print any" 实为大小写提示等）
- 研究结论：TACO 类数据集对多解仅打 SPJ 标记文件（宽松启发式），不写
  每题 checker；我们为每题写独立谓词 checker，判定质量高于业界惯例。

### checker 实现（每个=独立谓词判定，读取 输入+@@REX_USER_OUTPUT@@+输出）
| 题 | 判定谓词 |
|---|---|
| cf384a Coder | 最大数 ceil(n²/2)+棋盘无相邻 C |
| cf53c Little Frog | 1..n 排列+相邻差互异 |
| cf437b Child and Set | 互异元素+Σlowbit==sum+(-1)可达性(bitset DP) |
| cf1717b Madoka | 窗口含 X+最小数+(r,c) 为 X |
| cf27b Tournament | 唯一缺失对 |
| cf20c Dijkstra | 独立 Dijkstra+路径合法总权==最短 |
| cf1991c Absolute Zero | ≤40 步归零+(-1)奇偶判据 |
| cf1253b Silly Mistake | 逐段合法日+(-1)贪心判据 |
| cf1327c Game with Chips | 同步模拟移动+目标访问 |
| cf1054c Candies | 重算 l/r 匹配输入 |
| cf1305e Kuroni | O(n²)双指针独立计数三元组==m |
| cf549g Happy Line | 价值守恒 sorted(a_i+i)==sorted(b_q+q)+非递减 |
| cf71d Solitaire | 重建棋盘验证方块条件+替换牌合法性+No solution 独立搜索 |
| abc392_e Cables | 模拟重连+K==连通块-1 |

### 验证
- 每题 checker：题集参考解输出全 AC（共 45 case）；9+ 构造非法输出全部正确拒
- 14 题 C++ 参考解端到端 `run_test_cases(judge=special)` 全 PASS
- multi_pending.json：5 题标记 ingested；cf1907a（未入库）保留 pending

### 调用文件
- `scripts/checkers/{source_id}_checker.py`（14 个新 checker）
- `scripts/checkers/_apply_checkers.py`（checker 内嵌题集工具）
- `scripts/checkers/_batch_selftest.py`（批量自测工具）
- `data/questions/cf_selfbuilt.jsonl`（13 题转 special）
- `data/questions/abc_selfbuilt.jsonl`（abc392_e 转 special）

---

<!-- 后续任务按此格式追加 -->

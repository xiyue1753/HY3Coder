# 数据源注册中心 · 映射与变更指南

> 全项目数据文件位置统一在 `src/rex/datasource.py`（**唯一权威**）声明。
> 其余代码（store / api / cli / make_report / 前端 / ingest 脚本）一律通过该模块
> 的访问器取路径，**不手写文件名**。因此「加 / 删 / 换数据源」只需改注册中心。

## 1. 数据集（Dataset）→ 文件映射

| dataset key | 题集（data/questions/） | 正式评测（data/outputs/） | refine（data/outputs/） | enabled |
|---|---|---|---|---|
| `abc_selfbuilt` | `abc_selfbuilt.jsonl` | `eval_selfbuilt_all.jsonl` | `refine_selfbuilt_all.jsonl` | ✅ |
| `cf_selfbuilt` | `cf_selfbuilt.jsonl` | —（尚未正式评测） | — | ✅ |
| `demo` | `demo_algorithm.jsonl` | — | — | ❌（演示，不计指标） |

## 2. 独立 artifact → 文件映射

| artifact | 目录 | 文件 |
|---|---|---|
| 交互评测记录 | data/outputs/ | `eval_interactive.jsonl` |
| 真实评测检出 golden（SILENT_FAILURE 留档） | data/golden/ | `golden_real_algorithm.jsonl` |
| 人工抽检标注 | data/outputs/ | `audit_records.jsonl` |
| 测试用例源 | data/cases/ | `{source_id}_cases.json` |

## 3. 主要消费方（只调访问器，不写字面量）

| 模块 | 使用的访问器 |
|---|---|
| `src/rex/store.py` | `active_eval_filenames()`（默认白名单）、`INTERACTIVE_EVAL` |
| `src/web/api.py` | `load_active_questions/evals/refines/golden/audits`、`audit_path` |
| `src/cli.py` | `_default_eval_out/_default_refine_out`（题集→数据集反查）、`audit_path` |
| `scripts/make_report.py` | `load_active_*`、`golden_real_path` |
| 前端提示 | 后端 `/api/meta` 下发 `audit_command` 等，不写死 |

## 4. 变更操作

### 4.1 删除一个数据集（如废弃 cf_selfbuilt）
把 `DATASETS` 中该条 `enabled=False`（推荐，可回退）或整条移除。
无需改任何其它代码——题集、评测、refine 读取自动跳过。

### 4.2 新增一个数据集
在 `DATASETS` 加一条 `Dataset(...)`（`enabled=False` 起步），
把题集文件放入 `data/questions/`；验证读取后置 `True`。
评测跑完后在字段里填 `evals`/`refine` 文件名，store/api/report 自动纳入。

### 4.3 换正式评测主源 / 新增评测文件
改对应数据集的 `evals`/`refine` 字段，或调整 `evals_path`/`refine_path` 规则。

### 4.4 废弃数据集命名（防复活）
`DEPRECATED_KEYS` 记录历史 key（algorithm/taco/math）；若未来引入 TACO
镜像题集，按**独立数据集**注册（如 `taco`），不得复用 `eval_algorithm.jsonl` 命名。

## 5. 历史归档（_archived/）

`data/outputs/_archived/` 存放已被全量覆盖的历史分片/旧格式，仅供追溯：
- `eval_selfbuilt_{bm,hard,smoke,fixverify}.jsonl`（ABC 评测分片，均为
  `eval_selfbuilt_all.jsonl` 175 题的精确子集）
- `eval_selfbuilt_all.json`（旧 JSON 数组格式，同 jsonl 全集）
- `audit_records_full.jsonl`（audit_records.jsonl 超集/冗余）

规则：归档文件不被任何代码读取；`data/outputs/*` 已在 .gitignore 排除，
归档目录不会提交。

## 6. 验证「删数据源不影响其它」的快速方法

```python
# 模拟禁用 cf_selfbuilt：注册中心只此一处改动
import sys; sys.path.insert(0, "src")
from rex import datasource as ds
ds.DATASETS = tuple(
    d if d.key != "cf_selfbuilt" else ds.Dataset(key=d.key, label=d.label,
        enabled=False, questions=d.questions, evals=d.evals,
        refine=d.refine, note=d.note)
    for d in ds.DATASETS)
qs = ds.load_active_questions(".")     # 立即只剩 ABC 175 题
evals = ds.load_active_evals(".")      # 评测仍为 175，统计不受损
```

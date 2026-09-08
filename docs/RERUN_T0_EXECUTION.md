# temperature=0 全量重跑执行单（2026-09-08）

> 目的：用 `REX_TEMPERATURE=0` 把当前 359 题（ABC 175 + CF 184）重新求解与评估，产出独立 t0 记录，不覆盖当前基线；跑完后统一刷新报告/抽检/手写数字。
> 读取侧接入：`REX_EVAL_SUFFIX=_t0`（`datasource.evals_path` 按后缀解析），详见 `DESIGN.md` §9.1。

## 0. 试跑验证（先做）

```powershell
cd D:\VS_Project\TencentsOpen\Hy3_APP2
$env:REX_TEMPERATURE = "0"
& "D:\ProgramData\anaconda3\python.exe" -m src.cli run-eval --questions abc_selfbuilt.jsonl --sample 5 --out eval_selfbuilt_all_t0.jsonl --concurrency 2
```

通过标准：完成 ~6 题，无 FAILED；记录字段齐（answer_correct/verdict/findings(severity)/arbiter）；arbiter 恒为 ARBITER（或少量 HUMAN_REVIEW）。

## 1. 全量生成（独立文件，不覆盖当前）

```powershell
$env:REX_TEMPERATURE = "0"
& "D:\ProgramData\anaconda3\python.exe" -m src.cli run-eval --questions abc_selfbuilt.jsonl --sample full --out eval_selfbuilt_all_t0.jsonl --resume
& "D:\ProgramData\anaconda3\python.exe" -m src.cli run-eval --questions cf_selfbuilt.jsonl   --sample full --out eval_cf_all_t0.jsonl     --resume
```

- 每题 4 次模型调用（solve + V1 + V2 + ARBITER 总仲裁），ABC 175 → ~700 次，CF 184 → ~736 次；
- 失败自动重试 2 次；断点续跑用 `--resume`（默认开）；单题最终失败记为 FAILED，不中断批次；
- 产出：`data/outputs/eval_selfbuilt_all_t0.jsonl`（175）、`eval_cf_all_t0.jsonl`（184）。

## 2. 报告刷新（读取侧切 t0）

```powershell
$env:REX_EVAL_SUFFIX = "_t0"
& "D:\ProgramData\anaconda3\python.exe" scripts\make_report.py --out reports\REPORT.md
# 完成后取消：Remove-Item Env:\REX_EVAL_SUFFIX
```

REPORT §1（主/副口径+minor-only 行）、§2 分层、§3 错误类型、§6 抽检、§7 留档自动刷新。

## 3. 抽检（人工工作）

基于 t0 记录重新生成分层模板 → 按 `data/audit/audit_rules.md` v4 回填 40 条 → 校验 → 同步替换 `data/audit/audit_records.jsonl` 副本。

```powershell
# 生成模板（示例；records 用 t0 eval 文件）
& "D:\ProgramData\anaconda3\python.exe" scripts\audit_sample.py --results data\outputs\eval_selfbuilt_all_t0.jsonl --questions data\questions\abc_selfbuilt.jsonl --sample 35 --out data\outputs\audit_records_t0.jsonl
```

## 4. 手写文档数字刷新清单

| 位置 | 内容 |
|---|---|
| `reports/TASK2_REPORT_DRAFT.md` §5/§7/§8 | 定位率/误报率/主副口径/能力边界读数 |
| `reports/PROCESS_EVAL_METHOD.md` §4.3 | 全量抽检三层数字 |
| `DESIGN.md` §9.1 | 基线行（如 CORRECT=干净+仅 minor 计数、SF/PI 分布） |
| `reports/REPORT.md`（若需对照说明数据版本） | 注明 t0 数据版本 |

## 5. 验证/回滚

- 当前基线 `eval_selfbuilt_all.jsonl` / `eval_cf_all.jsonl` 全程不被触碰；去掉 `REX_EVAL_SUFFIX` 即回到旧基线视图；
- 失败处理：任何一步失败不中断；`--resume` 续跑；仍失败的题目在报告里可见（FAILED 计数）。

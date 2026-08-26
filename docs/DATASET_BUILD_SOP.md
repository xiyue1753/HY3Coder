# 自建算法评测集 · 标准操作说明（SOP）

> 从 AtCoder ABC / Codeforces 自建算法评测集（含题面 + 参考解 + 测试用例），
> 流程已验证可行（AtCoder 3 题 + CF 2 题入库）。

## 0. 前置环境

- Python 解释器：`D:\.conda\envs\tensor_env\python.exe`（用 `.\run.ps1` 或直接调用）
- C++ 编译：MSYS2 g++（`D:\msys64\ucrt64\bin\g++.exe`），沙盒已支持 C++ 编译运行
- 浏览器：系统 Edge（playwright `channel="msedge"`，不需下载浏览器、不写 C 盘）
- **禁止写 C 盘**（AppData 等目录有权限问题且用户明确禁止）

## 1. 两种数据源流程对比

| 环节 | AtCoder ABC | Codeforces |
|---|---|---|
| 题面抓取 | requests 直接抓 `<span class="lang-en">` | playwright+Edge 过 Cloudflare，`.problem-statement` |
| 登录 | 不需要（submission 页公开） | **需要**（JSESSIONID cookie，绕开 Turnstile） |
| 找 C++ AC 解 | kenkoooo API 查 submission ID → 抓源码 | 提交列表 `?order=BY_CONSUMED_TIME_ASC` 找 C++ AC → 抓源码 |
| 沙盒验证 | C++ 编译运行 | 同左 |

## 2. 入库脚本

```
scripts/ingest_abc.py   # AtCoder：--contest abc328 --problem b --submission <id> --cases-file ...
scripts/ingest_cf.py    # Codeforces：--contest 1 --index A --cases-file ...（需 CF_JSESSIONID 环境变量）
```

测试用例统一放 `data/cases/<source_id>_cases.json`（**人工设计**，含题面样例 + 自建边界）。

## 3. 标准操作步骤（每道题）

1. **选题**：选适合的 ABC（难度映射：100分→basic, 200-400→medium, 500+→hard）或 CF 题
2. **抓题面**：AtCoder 用 requests，CF 用 playwright（脚本内自动）
3. **拿参考解**：抓 C++ AC 解（AtCoder 用 kenkoooo API + submission 页；CF 用提交列表 + submission 页）
4. **人工设计测试用例**：读题理解约束 → 设计输入（边界/规律/最大最小）→ 期望输出**用 AC 解跑出**（不要手写，易算错）→ 写入 `data/cases/*.json`
5. **入库**：运行 ingest 脚本，自动写 `abc_selfbuilt.jsonl` / `cf_selfbuilt.jsonl`
6. **沙盒核对**：用全部测试用例跑参考解，确认 PASS

## 4. 关键要点与坑

- **期望输出必须用 AC 解跑出**，不要手写（曾因手写 ABC139 A 期望算错）。
- **CF 源码需清理非 ASCII 空白**（`\xa0` 等导致编译失败），ingest_cf.py 已处理。
- **CF 找 C++ AC 解**：提交列表用 `?order=BY_CONSUMED_TIME_ASC`（从最早提交找，老题早期是 C++）；默认时间倒序是最近提交（可能是其他语言）。
- **CF 登录**：Turnstile 无法自动化，需用户手动登录导 JSESSIONID，用 `$env:CF_JSESSIONID="xxx"` 传入（安全隔离，不落盘不入 git）。
- **AtCoder**：题面 `\leq`→`≤`、`D _ i`→`D_i` LaTeX 需转可读文本（保留英文原味）。

## 5. 质量要求（对齐任务书）

- 每道题：明确标准答案（= 可执行参考解代码 + 测试用例沙盒验证）+ 可自动校验判定
- 难度分层：basic/medium/hard + `layer_basis` 说明（官方分值/rating 映射或启发式）
- 测试用例：题面样例 + 人工设计边界（≥ 3 个，含最大/最小/特殊）
- 来源标注：`source="AtCoder-自建"` / `"Codeforces-自建"` + `source_id`（可溯源）

## 6. 验证

```bash
# 沙盒核对参考解通过全部用例
python -c "from rex.executor.tests import run_test_cases; ..."
# browse 页查看自建题
http://127.0.0.1:8000/browse?source=AtCoder   # 或 source=Codeforces
```

## 7. 安全隔离

- CF JSESSIONID：仅环境变量传入，不写入项目文件/脚本/git/文档
- 参考解来源：AtCoder submission（公开）、CF submission（用户授权登录后获取）

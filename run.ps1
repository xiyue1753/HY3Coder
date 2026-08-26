# =============================================================================
# ReAgents v2 统一运行脚本
# -----------------------------------------------------------------------------
# 目的：固化 conda 虚拟环境 tensor_env（Python 3.9）的调用方式，避免误用
#       系统 python（WindowsApps stub，会报 exit 9009）。
#
# 用法：
#   .\run.ps1 test                 # 运行全部 pytest 测试
#   .\run.ps1 run-eval math 5      # 评估数学 5 题（可再传 --concurrency 等）
#   .\run.ps1 run-refine math 5    # 修正模式（ReAct 闭环）
#   .\run.ps1 report               # 生成 reports/REPORT.md
#   .\run.ps1 serve                # 启动仪表盘 http://127.0.0.1:8000
#   .\run.ps1 py "print(1)"        # 直接用该环境 python 执行一段代码
#   .\run.ps1 exec <args...>       # 直接透传任意 python -m 参数
#
# 环境变量覆盖：
#   REX_PYTHON  指定 python 可执行文件绝对路径（默认 tensor_env）
# =============================================================================
param()

# 若用户显式指定了解释器则优先使用，否则用 tensor_env 的 python
if ($env:REX_PYTHON) {
    $PY = $env:REX_PYTHON
} else {
    $PY = "D:\.conda\envs\tensor_env\python.exe"
}

if (-not (Test-Path $PY)) {
    Write-Error "找不到 Python 解释器：$PY`n请设置环境变量 REX_PYTHON 指向可用的 python.exe。"
    exit 1
}

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ROOT

$cmd = $args[0]
if (-not $cmd) {
    Write-Host "用法见脚本头部注释。当前解释器：$PY"
    exit 0
}

switch ($cmd) {
    "test" {
        & $PY -m pytest tests/ -q
    }
    "run-eval" {
        $scene = if ($args[1]) { $args[1] } else { "math" }
        $sample = if ($args[2]) { $args[2] } else { "5" }
        # 透传剩余参数（如 --concurrency 4 --retries 2）
        $rest = @($args[3..($args.Length - 1)])
        & $PY -m src.cli run-eval --scene $scene --sample $sample @rest
    }
    "run-refine" {
        $scene = if ($args[1]) { $args[1] } else { "math" }
        $sample = if ($args[2]) { $args[2] } else { "5" }
        $rest = @($args[3..($args.Length - 1)])
        & $PY -m src.cli run-refine --scene $scene --sample $sample @rest
    }
    "report" {
        & $PY -m src.cli report
    }
    "serve" {
        & $PY -m src.cli serve
    }
    "py" {
        # .\run.ps1 py "代码字符串"
        & $PY -c $args[1]
    }
    "exec" {
        # .\run.ps1 exec -m <module> <args...>  直接透传
        $rest = @($args[1..($args.Length - 1)])
        & $PY $rest
    }
    default {
        Write-Error "未知命令：$cmd（支持 test/run-eval/run-refine/report/serve/py/exec）"
        exit 1
    }
}
exit $LASTEXITCODE

"""为 AtCoder 自建题补充隐藏边界测试用例。

设计原则：
1. 每道题按约束补充 3~5 个**合法边界输入**（最小规模/极端值/关键分支）。
2. 期望输出**由已验证的参考解自动生成**（参考解已通过官方样例，
   用其生成隐藏期望避免手算错误——见流程规则）。
3. 追加为 hidden=true 用例，写入 abc_selfbuilt.jsonl。

用法：
    python scripts/gen_hidden_cases.py [--ids A1011 A1012 ...]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rex.executor.sandbox import run_code  # noqa: E402
from rex.models import QuestionItem  # noqa: E402

OUT = ROOT / "data" / "questions" / "abc_selfbuilt.jsonl"

# source_id -> 合法边界输入列表（用 \n 换行）。期望输出自动生成。
BOUNDARY_INPUTS: dict[str, list[str]] = {
    # 并查集：单点无边 / 单点自环 / 链
    "abc292_d": [
        "1 0",
        "1 1\n1 1",
        "2 1\n1 2",
        "4 3\n1 2\n2 3\n3 4",
    ],
    # 树 DFS：两节点 / 星形 / 链
    "abc213_d": [
        "2\n1 2",
        "3\n1 2\n1 3",
        "4\n1 2\n2 3\n3 4",
    ],
    # 0-1 BFS：无开关直连不可达 / 有开关可达
    "abc277_e": [
        "2 1 0\n1 2 1",
        "2 1 1\n1 2 0\n1",
        "3 2 0\n1 2 1\n2 3 1",
    ],
    # 字符画：无边角
    "abc300_c": [
        "3 3\n...\n.#.\n...",
        "4 4\n#...\n.#..\n..#.\n...#",
        "3 3\n#.#\n.#.\n#.#",
    ],
    # 括号栈：空括号 / 同层冲突 / 跨层释放
    "abc283_d": [
        "()",
        "(ab)",
        "(a(b)c)",
        "(a(b)a)",
    ],
    # DP：K=1 / 全取 / 不可行
    "abc281_d": [
        "3 1 1\n5 10 15",
        "2 2 1\n3 4",
        "1 1 5\n10",
        "3 3 2\n1 1 1",
    ],
    # 数论：N=1 / 大 N
    "abc290_d": [
        "2\n1 1 1\n2 2 1\n5 5 3",
        "1\n1000000000 999999937 1",
    ],
    # 贪心区间：全重叠 / 全分离 / D=1
    "abc230_d": [
        "3 100\n1 10\n5 6\n9 9",
        "3 1\n1 1\n2 2\n3 3",
        "1 5\n1 1",
    ],
    # 判环：链 / 自环
    "abc285_d": [
        "1\na b",
        "3\na b\nb c\nc d",
    ],
    # 有序集合：重复插入 / 查小于等于边界
    "abc241_d": [
        "5\n1 5\n1 5\n2 5 1\n3 5 1\n2 5 2",
        "3\n2 100 1\n1 1\n2 100 2",
    ],
    # BFS：直接可达 / 不可达 / a=1 边界
    "abc235_d": [
        "2 2",
        "3 3",
        "2 999999",
    ],
    # 前缀和：全零 / 单元素
    "abc233_d": [
        "1 0\n0",
        "3 0\n0 0 0",
        "5 3\n1 2 0 1 2",
    ],
    # DP 装箱：单菜 / 已平衡
    "abc204_d": [
        "1\n7",
        "2\n5 5",
        "3\n1 2 3",
    ],
    # 并查集/度数：无约束 / 星形不可行
    "abc231_d": [
        "3 0",
        "5 4\n1 2\n1 3\n1 4\n1 5",
        "3 2\n1 2\n2 3",
    ],
    # 模拟：未叫先办（非法）→ 仅合法输入；全流程
    "abc294_d": [
        "3 6\n1\n1\n2 1\n3\n2 2\n3",
    ],
    # 博弈：N=1 / 只取1
    "abc270_d": [
        "1 1\n1",
        "5 1\n1",
        "8 3\n1 2 3",
    ],
    # BFS 计数：直接边 / 三角 / 不可达
    "abc211_d": [
        "2 1\n1 2",
        "3 3\n1 2\n2 3\n1 3",
        "4 4\n1 2\n1 3\n2 4\n3 4",
        "3 0",
    ],
    # ============ 第 2 轮（A1028-A1044）============
    # 250-like Number: N=1 最小 / 边界 p^3
    "abc250_d": ["1", "2", "100", "1000000000000000000"],
    # gcd 分治: N=2 / 全同
    "abc276_d": [
        "2\n2 3",
        "3\n6 6 6",
        "4\n2 3 4 6",
    ],
    # 网格 BFS: 单点 / 链
    "abc269_d": [
        "1\n0 0",
        "3\n0 0\n1 0\n2 0",
        "2\n0 0\n1 1",
    ],
    # 多源 BFS: 单点即守卫 / 两守卫
    "abc305_e": [
        "2 1 1\n1 2\n1 1",
        "3 2 2\n1 2\n2 3\n1 2\n3 2",
    ],
    # DP 背包: 单菜 / 全 a
    "abc271_d": [
        "1 5\n2 3",
        "2 4\n1 3\n1 3",
        "1 10\n5 5",
    ],
    # DP 选择: N=1 / 全负
    "abc267_d": [
        "1 1\n5",
        "2 2\n-1 -2",
        "3 2\n1 2 3",
    ],
    # DP 规划(Maximize Rating): 单元素 / 全选 / 递增
    "abc327_e": [
        "1 1\n1",
        "2 2\n5000 1",
        "4 2\n2 4 3 1",
    ],
    # DP 环计数: N=2 边界 / 小环
    "abc307_e": [
        "2 2",
        "2 1000000",
        "3 3",
    ],
    # BFS/字符串: atcoder 排列（固定7字符，各字母恰好一次）
    "abc264_d": ["atcoder", "coderta", "tacoedr", "redtoac"],
    # 字符串 LCP: 相同串 / 前缀关系
    "abc287_e": [
        "2\nab\nab",
        "3\na\nab\nabc",
        "4\nabc\nabd\nabe\nabf",
    ],
    # DFS 划分: 单成员 / T=N / T=1 / M=2 两对
    "abc310_d": [
        "3 3 0",
        "4 1 0",
        "3 2 1\n1 2",
        "3 2 2\n1 2\n1 3",
    ],
    # 组合计数: 全同 / 小 N
    "abc318_e": [
        "3\n1 1 1",
        "5\n1 2 3 4 5",
        "6\n1 2 1 2 1 2",
    ],
    # 优先队列: 单事件 / 无人排队
    "abc320_e": [
        "1 1\n1 5 3",
        "2 1\n1 5 3",
        "3 3\n1 10 1\n2 5 2\n3 3 3",
    ],
    # 滑动窗口: 窗口=全 / K=1
    "abc281_e": [
        "3 3 1\n1 2 3",
        "4 2 2\n5 5 5 5",
        "5 3 2\n9 1 8 2 7",
    ],
    # 二分+图: 两点 / 直线
    "abc257_d": [
        "2\n0 0 1\n1 0 1",
        "3\n0 0 1\n1 0 2\n2 0 1",
        "3\n-1 0 1\n0 0 1\n1 0 1",
    ],
    # 浮点边界: 最小/大
    "abc279_d": ["1 1", "2 1", "1000000000000000000 1000000000000000000"],
    # DFS 计数: 无环直链 / 单边
    "abc284_e": [
        "2 1\n1 2",
        "3 2\n1 2\n2 3",
        "4 3\n1 2\n2 3\n3 4",
    ],
    # ============ 第 3 轮（A1045-A1078）============
    # 246_d: 找 >=N 的最小 a^3+a^2b+ab^2+b^3
    "abc246_d": ["0", "1", "1000000000000000000"],
    # 291_e: 排列唯一性（拓扑）
    "abc291_e": ["2 1\n1 2", "3 3\n1 2\n2 3\n1 3"],
    # 292_e: 可达性计数
    "abc292_e": ["3 0", "3 2\n1 2\n2 3"],
    # 293_d: 绳两端颜色
    "abc293_d": ["2 1\n1 R 2 B", "3 0", "2 2\n1 R 1 B\n2 R 2 B"],
    # 294_e: 2xN 网格区间
    "abc294_e": ["1 1 1\n1 1\n1 1", "3 1 1\n1 3\n1 3"],
    # 295_d: 数字串切分
    "abc295_d": ["0", "1", "1234567890"],
    # 298_d: 字符串追加删除
    "abc298_d": ["3\n1 5\n2\n3", "5\n1 1\n1 2\n1 3\n2\n3"],
    # 302_e: 图边增删（1 u v 加边, 2 v 删边；每操作后打印孤立点数）
    "abc302_e": ["2 2\n1 1 2\n2 1", "3 3\n1 1 2\n2 2\n1 2 3"],
    # 303_e: 星形构造
    "abc303_e": ["3\n1 2\n2 3", "7\n1 2\n1 3\n1 4\n2 5\n2 6\n3 7"],
    # 304_e: 连通性禁令查询（格式：N M\n边\nK\n(x,y)*K\nQ\n(a,b)*Q）
    "abc304_e": ["3 2\n1 2\n2 3\n1\n1 3\n2\n1 3\n2 3", "2 1\n1 2\n1\n1 2\n1\n1 2"],
    # 308_d: 网格 sng 路径
    "abc308_d": ["2 3\nsng\nnmg", "2 2\nsn\ngg"],
    # 309_e: 树上保险继承
    "abc309_e": ["2 1 1\n1\n1 1", "3 2 1\n1 1\n1 1"],
    # 311_e: 无洞正方形计数
    "abc311_e": ["2 2 0", "3 3 1\n1 1"],
    # 317_e: 视线避让（S/G 大写）
    "abc317_e": ["2 2\nS.\n.G", "3 3\nS..\n...\n..G"],
    # 314_e: 轮盘期望
    "abc314_e": ["1 1\n1 1 1", "2 2\n1 1 2\n1 1 1"],
    # 252_d: 不同三元组计数
    "abc252_d": ["3\n1 1 1", "4\n1 2 3 4"],
    # 274_d: 折线可达（格式 N X Y / 随后 N 个步长）
    "abc274_d": ["2 3 1\n1 1", "3 5 1\n1 1 1"],
    # 295_d: 数字串分段（奇偶计数）
    "abc295_d": ["00", "11"],
    # 309_e: 树上保险
    "abc309_e": ["3 1 1\n1 1\n1 1"],
    # 242_e: 回文构造
    "abc242_e": ["1\n1\nA", "1\n2\nAA"],
    # 280_e: 期望概率
    "abc280_e": ["1 50", "2 50"],
    # 282_e: 最大生成树和
    "abc282_e": ["2 5\n1 2", "3 3\n1 1 1"],
    # 283_e: 行隔离最小翻转
    "abc283_e": ["2 2\n0 0\n0 0", "3 3\n1 0 1\n0 1 0\n1 0 1"],
    # 288_e: 必买组合
    "abc288_e": ["2 2\n5 5\n1 1\n1 2", "3 1\n1 1 1\n1 1 1\n1"],
    # 289_e: 图上回合最优（格式：T, N M, C_1..C_N, M 边）
    "abc289_e": ["1\n2 1\n0 1\n1 2", "1\n2 1\n1 0\n1 2"],
    # 296_e: 自循环不动点
    "abc296_e": ["1\n1", "3\n1 2 3"],
    # 297_e: 第K小组合和
    "abc297_e": ["1 1\n1", "2 3\n1 2"],
    # 301_e: 网格糖果（复用官方小样例）
    "abc301_e": ["2 2 1\nS.\n.G", "2 3 3\nS.o\n..G"],
    # 312_e: 立方体贴面
    "abc312_e": ["2\n0 1 0 1 0 1\n1 2 1 2 1 2", "1\n0 1 0 1 0 1"],
    # 313_e: 数字串递推
    "abc313_e": ["2\n11", "3\n121"],
    # 315_e: 读书依赖（格式：N / 随后 N 行 c_i 及其前置书目）
    "abc315_e": ["1\n0", "2\n1 2\n0"],
    # 321_e: 完全二叉树
    "abc321_e": ["1\n1 1 0", "1\n2 1 1"],
    # 323_e: 播放列表概率
    "abc323_e": ["2 1\n1 1", "3 3\n1 2 3"],
    # 286_e: 城市间最大价值（格式：N, A[], N 行边矩阵, Q, 查询）
    "abc286_e": ["2\n1 1\nNY\nYN\n1\n1 2", "3\n1 1 1\nNYY\nYNY\nYYN\n1\n1 2"],
    # 299_e: 黑点距离约束（格式：N M / M 条边 / K / K 行 x d）
    "abc299_e": ["2 1\n1 2\n0", "3 2\n1 2\n2 3\n1\n3 0"],
    # 306_e: 前K大维护
    "abc306_e": ["3 2 3\n2 0\n3 0\n1 0", "2 1 2\n1 5\n2 3"],
    # ============ 第 4 轮（A1079-A1102）============
    # 258_d Trophy: N=1 / X 全在最后一关
    "abc258_d": ["1 1\n1 1", "2 3\n1 10\n1 1", "1 1000000000\n1000000000 1000000000"],
    # 284_c 连通分量: 无边 / 两分量 / 单边全连通
    "abc284_c": ["3 0", "4 2\n1 2\n3 4", "2 1\n1 2"],
    # 255_d ±1 操作: N=1 / 全 0 / 最大查询
    "abc255_d": ["1 1\n0\n5", "2 2\n0 0\n0\n0", "1 1\n1000000000\n0"],
    # 272_d Root M Leaper: 1x1 / 小网格不可达
    "abc272_d": ["1 1", "3 1", "2 1"],
    # 196_c Doubled: 最小 / 边界
    "abc196_c": ["11", "22", "99"],
    # 198_c Compass Walking: 整步达 / 精确半径
    "abc198_c": ["5 15 0", "1 1 1", "1 0 1"],
    # 201_c Secret Number: 全 o / 全 x / 全 ?
    "abc201_c": ["oooooooooo", "xxxxxxxxxx", "??????????"],
    # 207_c Many Segments: 全同类相交
    "abc207_c": ["3\n1 1 2\n1 2 3\n1 3 4", "2\n2 1 2\n3 1 2"],
    # 209_c Not Equal: 降序大值 / 全 1
    "abc209_c": ["1\n1", "3\n1 1 1", "3\n3 2 1"],
    # 210_c Colorful Candies: 全同色 / 全不同
    "abc210_c": ["3 1\n1 1 1", "5 5\n1 2 3 4 5"],
    # 211_c chokudai: 最小串 / 无子序列
    "abc211_c": ["chokudaic", "chokudai", "cccccccc"],
    # 214_c Distribution: 最小 / 全同速率
    "abc214_c": ["2\n1 1\n1 1", "1\n5\n7", "3\n2 2 2\n3 3 3"],
    # 220_d FG operation: 最小 / 全同
    "abc220_d": ["2\n1 1", "3\n2 2 2", "2\n0 9"],
    # 225_d Play Train: 连后断 / 单点
    "abc225_d": ["2 3\n1 1 2\n2 1 2\n3 1", "1 1\n3 1", "3 2\n1 1 3\n3 2"],
    # 226_d Teleportation: 共线两向量 / 直角
    "abc226_d": ["2\n0 0\n0 1", "2\n0 0\n1 0", "3\n0 0\n1 1\n2 2"],
    # 237_d LR insertion: 单字符 / 全 L / 全 R
    "abc237_d": ["1\nR", "3\nLLL", "3\nRRR"],
    # 219_d Strange Lunchbox: 单盒 / 刚好达到 / 不可达
    "abc219_d": ["1\n1 1\n1 1", "2\n2 2\n1 1\n1 1", "1\n2 2\n1 1"],
    # 221_d Online games: 单人 / 相连区间
    "abc221_d": ["1\n1 1", "2\n1 2\n2 3"],
    # 228_d Linear Probing: 空表 / 插入同一槽
    "abc228_d": ["2\n1 0\n2 0", "2\n1 1\n2 1", "3\n1 0\n2 0\n2 1"],
    # 234_d Prefix K-th Max: K=N / K=1
    "abc234_d": ["3 3\n1 2 3", "3 1\n3 1 2"],
    # 239_d Prime Sum Game: 边界
    "abc239_d": ["1 1 2 2", "1 1 100 100", "2 2 3 3"],
    # 243_d Moves on Binary Tree: 叶上移 / 左右回移（X 需非根以支持 U）
    "abc243_d": ["2 2\nU", "2 1\nRL", "2 2\nLL"],
    # ============ 第 5 轮（A1105-A1128）============
    # 333_c Repunit Trio: 最小 / 边界
    "abc333_c": ["1", "2", "333"],
    # 336_c Even Digits: 最小 / 进位边界
    "abc336_c": ["1", "5", "1000000000000"],
    # 342_c Many Replacement: 无替换 / 单替换
    "abc342_c": ["1\na\n1\na a", "2\nab\n1\nb a"],
    # 343_c 343: 单值 / 边界
    "abc343_c": ["1", "8", "1000000000000000000"],
    # 349_c Airport Code: 子序列匹配 / 含X规则 / 不匹配
    "abc349_c": ["abc\nABC", "aab\nABX", "abc\nABD"],
    # 351_c Merge the balls: 单球 / 全等
    "abc351_c": ["1\n1", "3\n2 2 2", "5\n1 1 1 1 1"],
    # 358_c Popcorn: 单选覆盖 / 全选
    "abc358_c": ["1 1\no", "2 2\noo\nxo"],
    # 360_c Move It: 单盒 / 已就位
    "abc360_c": ["1\n1\n1", "2\n1 2\n1 1"],
    # 340_c Divide and Divide: 最小
    "abc340_c": ["3", "2", "4"],
    # 340_d Super Takahashi Bros: 最小链
    "abc340_d": ["2\n1 2 1", "3\n1 2 2\n2 3 1"],
    # 343_d Diversity of Scores: 单次 / 回零?
    "abc343_d": ["1 1\n1 5", "2 2\n1 3\n2 1"],
    # 344_d String Bags: 最小可行 / 每组一选 / 不可行
    "abc344_d": ["ab\n2\n1 a\n1 b", "ab\n1\n1 ab", "z\n1\n1 a"],
    # 345_c One Time Swap: 全同 / 单字符
    "abc345_c": ["aa", "ab", "aaa"],
    # 346_c Sigma: 单元素
    "abc346_c": ["1 1\n5", "2 1\n1 2"],
    # 349_d Divide Interval: 单点 / 最小
    "abc349_d": ["0 1", "1 2", "2 3"],
    # 350_d New Friends: 空图 / 单边
    "abc350_d": ["2 0", "3 1\n1 2"],
    # 336_e Digit Sum Divisible: 最小 / 边界
    "abc336_e": ["1", "10", "100000000000000"],
    # 338_d Island Tour: 最小环
    "abc338_d": ["3 2\n1 2", "4 3\n1 2 3"],
    # 341_d Only one of two: 最小（N≠M 为题设约束，禁止 N=M）
    "abc341_d": ["1 100000000 10000000000", "1 99999999 100000000"],
    # 346_d Gomamayo: 最短串
    "abc346_d": ["2\n11\n1 2", "2\n01\n1 2"],
    # 357_d 88888888: 最小
    "abc357_d": ["1", "2", "3"],
    # ============ 第 6 轮（A1129-A1152）============
    # 361_c Make Them Narrow: 最小 K / 大 K
    "abc361_c": ["2 1\n1 5", "3 1\n1 5 9", "4 2\n1 2 8 9"],
    # 363_c Avoid K Palindrome: 最小
    "abc363_c": ["3 2\naba", "5 3\nabcde", "4 3\naaaa"],
    # 365_c Transportation: 预算全覆盖 / 单日
    "abc365_c": ["1 5\n10", "3 100\n1 1 1", "2 5\n10 10"],
    # 366_c Balls and Bag: 插入查询 / 删除后
    "abc366_c": ["3\n1 1\n3\n3", "4\n1 5\n1 5\n2 5\n3"],
    # 368_c Triple Attack: 单怪 / 短血
    "abc368_c": ["1\n1", "1\n2", "2\n2 2"],
    # 370_c Word Ladder: 已等 / 反转
    "abc370_c": ["ab\nab", "ab\nba", "abc\nabc"],
    # 373_c Max Ai+Bj: 单元素 / 两端
    "abc373_c": ["1\n10\n20", "2\n1 5\n2 6"],
    # 362_d Shortest Path 3: 最小图
    "abc362_d": ["2 1\n1 1\n1 2 5", "3 2\n1 1 1\n1 2 1\n2 3 1"],
    # 364_d K-th Nearest: 单点
    "abc364_d": ["1 1\n5\n3 1", "2 1\n1 10\n6 1"],
    # 365_d Janken 3: 最短
    "abc365_d": ["1\nR", "2\nRS", "3\nRSP"],
    # 367_d Pedometer: 小环
    "abc367_d": ["2 3\n1 1", "3 3\n1 1 1"],
    # 371_d 1D Country: 单点人口 / 双查询
    "abc371_d": ["1\n0\n5\n2\n-5 5\n10 20", "2\n1 3\n10 20\n1\n0 5"],
    # 372_d Buildings: 单建筑 / 降序
    "abc372_d": ["1\n1", "3\n3 2 1"],
    # 361_e Tree Hamilton: 单边树
    "abc361_e": ["2\n1 2 5", "3\n1 2 1\n2 3 1"],
    # 362_e Count Arith Subseq: 全等 / 等差
    "abc362_e": ["2\n5 5", "3\n1 2 3", "3\n2 2 2"],
    # 363_e Sinking Land: 最小网格
    "abc363_e": ["1 1 1\n1", "2 2 5\n1 1\n1 1"],
    # 365_e Xor Sigma: 小数组
    "abc365_e": ["2\n1 2", "3\n1 1 1", "3\n1 2 3"],
    # 367_e Permute K: K=0 / K=1
    "abc367_e": ["2 0\n2 1\n1 2", "2 1\n2 1\n1 2", "3 1\n2 3 1\n1 2 3"],
    # 368_d Steiner Tree: 单点必含
    "abc368_d": ["2 2\n1 2\n1 2", "3 2\n1 2\n2 3\n1 3"],
    # 370_e Avoid K Partition: 单段
    "abc370_e": ["1 5\n1", "2 5\n1 1", "2 10\n2 8"],
    # 372_e K-th LCC: 单查询
    "abc372_e": ["2 2\n1 1 2\n2 1 1", "3 3\n1 1 2\n2 3 1\n2 3 2"],
    # 375_d ABA: 单字符 / 小串
    "abc375_d": ["A", "ABA", "AAAA"],
    # 375_e 3 Team: 最小三队
    "abc375_e": ["3\n1 1\n2 1\n3 1", "3\n1 2\n2 3\n3 4"],
    # ============ 第 7 轮（A1153-A1175）============
    # 376_c Prepare Another Box: N A 行 B 行（N>=2）
    "abc376_c": ["2\n1 1\n1", "2\n3 1\n5"],
    # 378_c Repeating: 全同/最小
    "abc378_c": ["3\n1 1 1", "1\n5", "4\n1 2 1 1"],
    # 380_c Move Segment: 最小
    "abc380_c": ["5 2\n10101", "6 2\n011001"],
    # 382_c Kaiten Sushi: 单调
    "abc382_c": ["2 1\n1 2\n1", "3 2\n3 2 1\n2 1"],
    # 384_c Perfect Standings: 单题
    "abc384_c": ["100 110 120 130 140", "200 300 400 500 600"],
    # 388_c Kagamimochi: 全等
    "abc388_c": ["2\n1 1", "3\n1 1 1"],
    # 392_c Bib: 单选手
    "abc392_c": ["2\n2 1\n1 2", "2\n1 2\n2 1"],
    # 389_c Snake Queue: 小队列（type2/3 需队非空）
    "abc389_c": ["3\n1 5\n3 1\n3 1", "4\n1 5\n1 3\n2\n3 1"],
    # 377_d Many Segments 2: 单区间 / 全覆盖
    "abc377_d": ["1 5\n2 3", "2 5\n1 1\n2 5"],
    # 381_d 1122 Substring: 最小成对 / 不可行
    "abc381_d": ["2\n1 1", "4\n1 1 2 2", "3\n1 2 3"],
    # 393_d Swap to Gather: 单1 / 全1
    "abc393_d": ["2\n10", "4\n1111", "3\n010"],
    # 376_d Cycle: 无环链 / 自对?
    "abc376_d": ["2 1\n1 2", "3 2\n1 2\n2 3"],
    # 378_e Mod Sigma: 单元素 / 全 0
    "abc378_e": ["1 5\n1", "2 5\n0 0"],
    # 386_e Maximize XOR: 最小组合
    "abc386_e": ["2 1\n1 2", "3 2\n1 2 4"],
    # 388_e Kagamimochi 2: 最小二分
    "abc388_e": ["2\n1 2", "3\n1 2 3"],
    # 389_e Square Price: 单价
    "abc389_e": ["1 5\n2", "2 5\n1 1"],
    # 392_e Cables: 最小连通
    "abc392_e": ["2 1\n1 2", "3 2\n1 2\n2 3"],
}


# ============ 补缺批次（2026-09-10）：原先缺隐藏用例的题 ============
BOUNDARY_INPUTS.update({
    # abc161_d Lunlun Number: K 最小值 / 邻近上界
    "abc161_d": ["2", "3", "50", "99999"],
    # abc224_d 8 Puzzle on Graph: M=0（无边）已解 / 未解
    "abc224_d": ["0\n1 2 3 4 5 6 7 8", "0\n2 3 4 5 6 7 8 9"],
    # abc236_d Dance: N=1 最小 / 全零 / 满值 2^30-1
    "abc236_d": [
        "1\n0",
        "2\n0 0 0\n0 0\n0",
        "2\n1073741823 0 1073741823\n1073741823 0\n1073741823",
    ],
    # abc339_d Synchronized Players: 相邻两玩家 / 对角 / 远距
    "abc339_d": ["2\nPP\n..", "2\nP.\n.P", "3\nP..\n...\n..P"],
    # abc348_d Medicines on Grid: 单行 / 单列 / 需药才可达
    "abc348_d": [
        "1 2\nST\n1\n1 1 1",
        "2 1\nS\nT\n1\n2 1 1",
        "2 2\nS.\n.T\n2\n1 1 1\n2 2 1",
    ],
    # abc351_d Grid and Magnet: 1x1 / 仅一格空地 / 单行交替
    "abc351_d": ["1 1\n.", "2 2\n##\n#.", "1 4\n.#.#"],
    # abc371_c Make Isomorphic: N=1 空图 / N=2 / N=3
    "abc371_c": ["1\n0\n0", "2\n0\n0\n1", "3\n2\n1 2\n2 3\n1\n1 3\n7 8\n9"],
    # abc379_d Home Garden: 仅 type3 / 种后即收 / T,H 上界
    "abc379_d": ["1\n3 1", "2\n1\n3 1", "3\n1\n2 1000000000\n3 1000000000"],
    # abc385_d Santa Claus 2: 起点极值 / 往返收集
    "abc385_d": [
        "1 1 0 0\n1000000000 1000000000\nR 1000000000",
        "2 2 0 0\n1 0\n-1 0\nL 1\nR 1",
    ],
    # abc386_d Diagonal Separation: N=1 单点 B / W / 小棋盘混合
    "abc386_d": [
        "1 1\n1 1 B",
        "1000000000 1\n1000000000 1 W",
        "2 3\n1 1 B\n2 1 W\n1 2 W",
    ],
    # abc395_d Pigeon Swap: 最小 / 搬巢后查询 / 连续交换
    "abc395_d": ["1 1\n3 1", "2 3\n1 1 2\n3 1\n3 2", "3 4\n2 1 2\n1 2 3\n3 2\n3 3"],
    # abc383_e Sum of Max Matching: 最小连通图 / K=N / 大权重
    "abc383_e": [
        "2 1 1\n1 2 5\n1\n2",
        "3 2 3\n1 2 1\n2 3 1\n1 2 3\n3 2 1",
        "2 1 2\n1 2 1000000000\n1 2\n2 1",
    ],
    # abc384_e Takahashi is Slime 2: 1x1 / 单行 / X 上界
    "abc384_e": [
        "1 1 1\n1 1\n1",
        "1 2 1\n1 1\n5 10",
        "2 2 1000000000\n2 2\n1000000000000 1000000000000\n1000000000000 1",
    ],
})


def run_output(code: str, inp: str) -> tuple[str | None, str]:
    """运行参考解，返回 (stdout, error)。"""
    res = run_code(code, stdin=inp, timeout=20, language="cpp")
    if res.error or res.timed_out:
        return None, res.error or "timeout"
    return res.stdout.rstrip(), ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", nargs="*", default=None)
    args = ap.parse_args()
    rows = [json.loads(l) for l in OUT.open(encoding="utf-8") if l.strip()]
    added = 0
    failed: list[str] = []
    for r in rows:
        sid = r["source_id"]
        if args.ids and r["id"] not in args.ids:
            continue
        inputs = BOUNDARY_INPUTS.get(sid)
        if not inputs:
            continue
        q = QuestionItem.model_validate(r)
        existing_hidden = {tc["input"] for tc in r["test_cases"] if tc.get("hidden")}
        new_cases = []
        for inp in inputs:
            if inp in existing_hidden:
                continue
            out, err = run_output(q.reference_solution, inp)
            if out is None:
                failed.append(f"{sid}: 输入 {inp!r} 运行失败: {err[:80]}")
                continue
            new_cases.append({"input": inp, "output": out, "hidden": True})
        if new_cases:
            r["test_cases"].extend(new_cases)
            added += len(new_cases)
            print(f"{r['id']} {sid}: +{len(new_cases)} 隐藏用例")
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"\n共新增 {added} 个隐藏用例")
    if failed:
        print("失败项：")
        for f in failed:
            print(" ", f)


if __name__ == "__main__":
    main()

"""为 Codeforces 自建题补充隐藏边界测试用例（对齐 ABC gen_hidden_cases.py）。

设计原则：
1. 每道题按约束补充 2~4 个**合法边界输入**（最小规模/极端值/关键分支）。
2. 期望输出**由已验证的参考解自动生成**（参考解已通过官方样例，
   用其生成隐藏期望避免手写算错——见流程规则）。
3. 追加为 hidden=true 用例，写入 cf_selfbuilt.jsonl。

用法：
    python scripts/gen_cf_hidden_cases.py [--ids C2003 C2004 ...]
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

OUT = ROOT / "data" / "questions" / "cf_selfbuilt.jsonl"

# source_id -> 合法边界输入列表（\n 换行；期望输出由参考解生成，不手写）
BOUNDARY_INPUTS: dict[str, list[str]] = {
    # 486A Calculating Function: 奇偶求和公式，n 可达 1e15
    "cf486a": ["1", "2", "999999999999999999", "1000000000000000000"],
    # 910A The Way to Home: 跳跃最短路（0/1 串，首尾为 1）
    "cf910a": [
        "2 1\n11",
        "5 4\n10001",
        "5 1\n10001",
        "10 9\n1000000001",
        "8 1\n11111111",
    ],
    # 1660A Vasya and Coins: 最小不可支付金额（a 个 1 分、b 个 2 分）
    "cf1660a": [
        "1\n1 1",
        "1\n0 1",
        "1\n1 0",
        "1\n1000000000 1000000000",
    ],
    # 1795A Two Towers: 两塔顶移动能否无相邻同色
    "cf1795a": [
        "1\n1 1\nR\nB",
        "1\n2 2\nBR\nRB",
        "1\n3 1\nBBB\nR",
        "1\n1 3\nR\nBRB",
    ],
    # 757A Gotta Catch Em' All!: 数 "Bulbasaur" 字母出现次数下限
    "cf757a": ["Bulbasaur", "F", "Bbulbbasaur", "aaaaaaaa"],
    # 1730A Planets: 相同轨道行星可整体移除（c）或逐个（1）
    "cf1730a": [
        "1\n1 1\n1",
        "1\n3 10\n1 1 1",
        "1\n3 1\n1 1 1",
        "2\n5 1\n1 1 2 2 3\n3 3\n1 2 3",
    ],
    # 110A Nearly Lucky Number: 4/7 数字个数是否为 4 或 7
    "cf110a": ["44", "4444", "7777777", "1", "1234567890"],
    # 96A Football: 是否含 7 个连续相同
    "cf96a": ["0000000", "00000001", "01010101", "11111110000", "1000000001"],
    # 144B Meeting: 矩形周界上有多少点不被任一暖气覆盖
    "cf144b": [
        "2 5 4 2\n3\n3 1 2\n5 3 1\n1 3 2",
        "2 2 3 3\n1\n2 2 1",
        "1 1 2 2\n1\n1 1 1",
    ],
    # 343B Alternating Current: 相邻同号成对消除后是否为空
    "cf343b": ["++", "--", "+-+-", "-++-", "++++"],
    # 455A Boredom: 选数最大分（相邻值被删除）
    "cf455a": [
        "1\n5",
        "4\n1 1 1 1",
        "3\n3 2 1",
        "5\n1 2 1 2 1",
    ],
    # 414B Mashmokh and ACM: 整除链计数
    "cf414b": ["1 1", "2 2", "5 3", "2000 2"],
    # 429A Xor-tree: 翻转子树最小次数
    "cf429a": [
        "1\n0\n1",
        "1\n1\n1",
        "2\n2 1\n0 0\n1 0",
    ],
    # 1060E Sergey and Subway: 加距离 2 边后的最短路和
    "cf1060e": [
        "2\n1 2",
        "5\n1 2\n2 3\n3 4\n4 5",
        "5\n1 2\n1 3\n1 4\n1 5",
    ],
    # 358D Dima and Hares: 喂兔顺序 DP
    "cf358d": [
        "1\n5\n3\n1",
        "2\n1 2\n2 1\n0 0",
        "3\n1 1 1\n1 2 1\n1 1 1",
    ],
    # 300C Beautiful Numbers: 好数计数
    "cf300c": ["1 2 1", "1 2 2", "1 9 100", "2 3 1000000"],
    # 676C Vasya and String: 最多改 k 个，最大同色连续段
    "cf676c": [
        "1 0\na",
        "10 1\nababababab",
        "10 2\naaaaaaaaaa",
        "3 2\naba",
        "10 10\nbbbbbbbbbb",
    ],
    # ============ CF 自建第 2 批（C2020-C2043）============
    # 137A Postcards and photos: 连续同字母块每趟最多 5 张
    "cf137a": [
        "C",
        "P",
        "CPCPCP",
        "CCCCC",
        "PPPPPP",
        "CCCCCCCCCC",
    ],
    # 519B A and B and Compilation Errors: 三行逐个删
    "cf519b": [
        "3\n1 2 3\n1 3\n3",
        "3\n5 5 5\n5 5\n5",
        "4\n10 20 30 40\n10 20 30\n10 20",
        "5\n1 1 1 1 1\n1 1 1 1\n1 1 1",
    ],
    # 1093E Intersection of Permutations: 排列区间交集 + b 上交换
    "cf1093e": [
        "4 3\n1 2 3 4\n4 3 2 1\n1 1 1 1 1\n2 1 4\n1 1 2 1 4",
        "2 1\n1 2\n1 2\n1 1 1 1 1",
        "3 2\n1 2 3\n1 2 3\n1 1 3 2 3\n1 2 2 1 3",
    ],
    # 2044G2 Medium Demon Problem: r_i 非自指映射
    "cf2044g2": [
        "1\n2\n2 1",
        "1\n3\n2 3 1",
        "2\n2\n2 1\n3\n3 1 2",
    ],
    # 1552F Telepanting: x 严格递增，y<x 且 2n 个位置互异
    "cf1552f": [
        "1\n5 2 0",
        "1\n5 2 1",
        "2\n3 1 0\n7 4 1",
        "3\n4 1 0\n8 3 1\n10 6 0",
    ],
    # 549G Happy Line: 判定可达 + 输出唯一 happy 线（有解时输出序列唯一）
    "cf549g": [
        "1\n5",
        "2\n1 1",
        "2\n0 0",
        "3\n3 2 1",
        "3\n5 0 0",
    ],
    # 1202C WASD-string: 移动后最小包围矩形面积
    "cf1202c": [
        "1\nW",
        "1\nA",
        "1\nWDSA",
        "1\nWWWW",
        "1\nWAWDSDSA",
    ],
    # 1249D1 Too Many Segments: 删除最少使每点覆盖 <=k
    "cf1249d1": [
        "1 1\n1 1",
        "2 1\n1 1\n1 1",
        "3 1\n1 1\n1 1\n1 1",
        "2 1\n1 1\n2 2",
        "1 1\n200 200",
    ],
    # 2254C2 Marenol: 变换二进制串（翻转/删除段?）
    "cf2254c2": [
        "1\n1\n0\n0",
        "1\n1\n0\n1",
        "1\n2\n01\n10",
        "1\n6\n110000\n000011",
    ],
    # 2241F A Bit Odd: 子串操作博弈（Alice/Bob）
    "cf2241f": [
        "1\n1\n1",
        "1\n1\n0",
        "1\n2\n01",
        "1\n5\n00000",
        "1\n5\n01010",
    ],
    # 1914E1 Game with Marbles: 双方轮流吃（n<=6 easy）
    "cf1914e1": [
        "1\n2\n1 1\n1 1",
        "1\n2\n5 1\n1 5",
        "1\n6\n1 1 1 1 1 1\n1 1 1 1 1 1",
        "1\n2\n1000000000 1\n1 1000000000",
    ],
    # 524B Round Photo: 每人可躺，最小面积
    "cf524b": [
        "1\n5 10",
        "2\n1 1\n1 1",
        "3\n10 1\n10 1\n10 1",
        "2\n1000 1000\n1000 1000",
    ],
    # 1737B Luxury Number: [l,r] 中形如 x^2, x^2+x, x^2+2x? 的计数
    "cf1737b": [
        "1\n1 1",
        "1\n1 1000000000000000000",
        "1\n1000000000000000000 1000000000000000000",
        "1\n8 9",
    ],
    # 1495A Diamond Miner: 矿工与矿配对求最小距离和（浮点，容差比对）
    "cf1495a": [
        "1\n1\n0 3\n2 0",
        "1\n2\n0 1\n0 4\n2 0\n5 0",
        "1\n2\n0 -1\n0 -3\n-2 0\n4 0",
        "1\n3\n0 100000000\n0 99999999\n0 1\n1 0\n2 0\n100000000 0",
    ],
    # 1833F Ira and Flamenco: 严格递增差 1 的 m 元组计数（mod 1e9+7）
    "cf1833f": [
        "1\n3 3\n1 2 3",
        "1\n5 1\n1 1 1 1 1",
        "1\n5 2\n1 2 3 4 5",
        "1\n4 2\n1 1 2 2",
    ],
    # 667B Coat of Anticubism: 无法成多边形，补最短杆使其可成凸多边形
    "cf667b": [
        "3\n2 1 1",
        "3\n1 1 1",
        "4\n10 1 1 1",
        "3\n1000000000 1 1",
    ],
    # 811A Vladik and Courtesy: 轮流给 1,3,5.. 个糖果
    "cf811a": [
        "1 1",
        "1 2",
        "2 1",
        "1000000000 1",
        "1000000000 1000000000",
    ],
    # 937A Olympiad: 非零不同分数的数量
    "cf937a": [
        "1\n1",
        "1\n600",
        "2\n600 600",
        "5\n1 2 3 4 5",
        "3\n0 1 0",
    ],
    # 2075D Equalization: x/y 除以 2^k 或补位最小代价
    "cf2075d": [
        "1\n0 0",
        "1\n1 1",
        "1\n0 1",
        "1\n100000000000000000 100000000000000000",
        "1\n100000000000000000 1",
    ],
    # 1548B Integers Have Friends: 最长同余段（相邻差 gcd>1）+1
    "cf1548b": [
        "1\n1\n5",
        "1\n2\n6 10",
        "1\n3\n2 4 6",
        "1\n4\n1000000000000000000 999999999999999999 999999999999999998 999999999999999997",
    ],
    # 1062D Fun with Integers: a->b->(-a)->(-b)->a 变换得分上限
    "cf1062d": ["2", "3", "4", "100000"],
    # 1200B Block Adventure: 跨列搬砖判定 YES/NO
    "cf1200b": [
        "1\n1 0 0\n5",
        "1\n2 0 5\n5 5",
        "1\n2 0 0\n5 0",
        "2\n3 0 1\n4 3 5\n2 0 0\n5 10",
    ],
    # 808B Average Sleep Time: k 长窗口和平均（浮点容差）
    "cf808b": [
        "1 1\n10",
        "3 3\n1 2 3",
        "4 2\n1 1 1 1",
        "3 2\n100000 1 1",
    ],
    # 1490D Permutation Transformation: 递归最大值建树求深度
    "cf1490d": [
        "1\n1\n1",
        "1\n2\n1 2",
        "1\n2\n2 1",
        "1\n4\n1 2 3 4",
        "1\n5\n5 4 3 2 1",
    ],
    # ============ CF 自建第 3 批（C2044-C2046）============
    # 1066D Boxes Packing: 从末尾开始尽量多装箱（贪心/二分）
    "cf1066d": [
        "1 1 1\n1",
        "2 1 10\n5 5",
        "5 2 6\n5 2 1 4 2",
        "3 3 1\n1 1 1",
        "5 1 4\n4 2 3 4 1",
    ],
    # 21C Stripe 2: 切成三段每段和相等
    "cf21c": [
        "1\n0",
        "2\n0 0",
        "3\n1 1 1",
        "4\n1 2 3 3",
        "6\n1 1 1 1 1 1",
    ],
    # 777B Game of Credit Cards: Moriarty 可重排的最小/最大挨弹数
    "cf777b": [
        "1\n1\n1",
        "1\n9\n0",
        "2\n88\n00",
        "2\n00\n88",
        "4\n1111\n9999",
        "4\n9999\n1111",
    ],
    # ============ CF 难档扩题（C2182-C2190，cf-github1）============
    # 86D Powerful array: 莫队，power = sum K_c^2*c
    "cf86d": [
        # 全相同 → 每个查询答案一致，验证 K 计数的平方项
        "3 2\n1 1 1\n1 3\n2 2",
        # 单元素最小
        "1 1\n5\n1 1",
        # 边界值 1e6 大数
        "2 2\n1000000 999999\n1 1\n1 2",
        # 空区间不可（l<=r）；n 上限小样例验证极端值
        "4 4\n2 2 2 2\n1 1\n1 4\n2 3\n4 4",
    ],
    # 52C Circular RMQ: 环形数组，0-based；区间加 + 环形 min
    "cf52c": [
        # 单元素环形（lf=rg 时整环）
        "1\n5\n3\n0 0\n0 0 2\n0 0",
        # 环形 wrap：lf>rg
        "4\n1 2 3 4\n3\n2 1\n2 1 -5\n1 0",
        # 负值区间加
        "3\n-1000000 0 1000000\n3\n1 2 -1000000\n1 1\n0 2",
        # 全相同 + 大区间
        "3\n7 7 7\n3\n0 2\n0 2 3\n1 1",
    ],
    # 938D Buy a Ticket: 虚源点 Dijkstra，往返=2*dist+当地票价取 min
    "cf938d": [
        # 星形全连接最小环
        "2 1\n1 2 10\n5 3",
        # 自留最便宜（每个城市直接本地听）
        "2 0\n1 1",
        # 大权重
        "3 2\n1 2 1000000000000\n2 3 1000000000000\n1000000000000 1 1",
        # 4 点链状往返
        "4 3\n1 2 1\n2 3 2\n3 4 3\n10 10 10 1",
    ],
    # 920F SUM and REPLACE: ai→d(ai)（因子个数），值快速收敛到 2/1
    "cf920f": [
        # 已收敛：全 2/1，REPLACE 后不变
        "3 4\n2 2 2\n1 1 3\n2 1 3\n1 2 2\n2 1 3",
        # 全 1
        "2 2\n1 1\n1 1 2\n2 1 2",
        # 大质数附近收敛
        "4 3\n1 1000000 999983 7\n2 1 4\n1 1 4\n2 1 4",
        # 单元素
        "1 2\n8\n1 1 1\n2 1 1",
    ],
    # 911E Stack Sorting: 已知前缀 p，补全排序序列（栈 + 贪心）
    "cf911e": [
        "2 1\n1",
        "3 1\n2",
        "4 2\n4 3",
        "5 4\n5 4 3 2",
        "3 2\n3 2",
    ],
    # 767C Garland: 树切两刀成 3 段每段温度相等（sum 被 3 整除）
    "cf767c": [
        # 3 节点各 0
        "3\n0 0\n1 0\n2 0",
        # 链，非 3 倍数段不可
        "3\n2 1\n3 2\n0 0",  # 总温度 0，分割后各 0
        # 星形
        "4\n0 1\n1 2\n1 3\n1 0",
        # 无解情形
        "4\n0 1\n1 2\n1 3\n1 1",  # 总温度 4，target 非整数
        # 温度可负
        "5\n0 1\n1 -2\n2 3\n3 -3\n3 2",  # 总温度 1，非整除 → -1
    ],
    # 710E Generate a String: 从空串生成 n 个 'a'：加 1 (x) 或翻倍 (y)
    "cf710e": [
        "1 1 1",
        "1 1 1000000000",
        "2 1 1",
        "3 1 3",   # 加一更优：1+1+1=3 vs 1+2+3? y=3 翻倍2 加1=... 期望参考解定
        "10 1 1",
        "10000000 1000000000 1",  # 大 n 全翻倍最优
    ],
    # 514C Watto and Mechanism: 三进制串精确改一位后是否在字典
    "cf514c": [
        "0 1\na",   # n=0 时查询必 NO
        "1 1\na\nb",
        "1 3\nabc\nbbc\nacc\nabd",
        "3 2\na\nb\nc\na\nb",  # 查原串须改一位 → NO
        "2 2\nab\nac\nbb\nba",
    ],
    # 29D Ant on the Tree: n<=300 叶序访问；路径唯一，不匹配输出 -1
    "cf29d": [
        # 星形 n=3 只有两叶
        "3\n1 2\n1 3\n2 3",
        # 链式
        "4\n1 2\n2 3\n3 4\n4",  # 只有 1 个叶
        # 三叉树两个叶
        "5\n1 2\n2 3\n1 4\n4 5\n5 3",
        # 非 DFS 可达叶序 → -1
        "6\n1 2\n1 3\n2 4\n2 5\n3 6\n5 4 6",
    ],
}


# ============ 补缺批次（2026-09-10）：原先缺隐藏用例的题 ============
BOUNDARY_INPUTS.update({
    # 609A USB Flash Drives: 单盘刚好 / 两盘需全用 / 满量
    "cf609a": ["1\n1\n1", "2\n1000\n500\n500", "100\n100000\n" + "1000\n" * 100],
    # 1811B Conveyor Belts: n=2 最小 / 满 n
    "cf1811b": ["2\n2 1 1 1 2\n4 4 4 1 1", "1\n1000000000 1 1 1000000000 1000000000"],
    # 1909F1 Small Permutation: n=1 两态 / 混合
    "cf1909f1": ["1\n1\n0", "1\n1\n1", "2\n2\n0 2\n3\n0 1 3"],
    # 950B Intercepted Message: 单块 / 等和各异
    "cf950b": ["1 1\n1\n1", "2 2\n1 2\n2 1", "3 1\n1 2 3\n6"],
    # 1996G Penacony: 最小 n / 完全图
    "cf1996g": ["1\n3 1\n1 2", "1\n3 3\n1 2\n1 3\n2 3"],
    # 1968G2 Division + LCP: 单字符 / 全同 / 非回文
    "cf1968g2": ["1\n1 1 1\na", "1\n3 1 3\naaa", "1\n2 2 2\nab"],
    # 1491D Zookeeper: u=v / u>v 极值
    "cf1491d": ["1\n1 1", "2\n1 2\n1073741823 1"],
    # 1009C Annoying Present: n=m=1 / 极值 x,d
    "cf1009c": ["1 1\n0 0", "2 2\n-1000 1000\n1000 -1000"],
    # 725B Food on the Plane: 最小行 / 行上界
    "cf725b": ["1a", "1000000000000000000f", "6c"],
    # 275B Convex Shape: 2x2 对角 / 单行
    "cf275b": ["2 2\nBW\nWB", "1 3\nBBB"],
    # 1073D Berland Fair: 单摊 / T 上界
    "cf1073d": ["1 1\n1", "2 1000000000000000000\n1000000000 1000000000"],
    # 513B1 Permutations(easy): n=1 / n 上界
    "cf513b1": ["1 1", "4 1", "8 1"],
    # 76D Plus and xor: 全零 / 64 位上界
    "cf76d": ["0\n0", "18446744073709551615\n18446744073709551615", "0\n18446744073709551615"],
    # 1912E Evaluate It and Back Again: 零 / 极值（special）
    "cf1912e": ["0 0", "1000000000000000000 -1000000000000000000"],
    # 508A Pasha and Pixels: 1x1 / 4 格成方块 / 格上界
    "cf508a": ["1 1 1\n1 1", "2 2 4\n2 2\n1 1\n2 1\n1 2", "1000 1000 1\n1000 1000"],
    # 1821D Black Cells: n=1 / 段相邻 / l,r 上界
    "cf1821d": ["1\n1 1\n1\n1", "1\n3 10\n1 5 10\n2 6 11", "1\n2 1000000000\n1 1000000000\n1 1000000000"],
    # 1868C Travel Plan: n=1 / n 上界
    "cf1868c": ["1\n1 1", "1\n1000000000000000000 100000", "1\n1 100000"],
    # 1988D Omnipotent Monster Killer: n=1 / 两测试点各最小
    "cf1988d": ["1\n1\n1", "2\n2\n1 2\n1 2\n3\n5 4 3\n1 2\n2 3"],
    # 617C Watering Flowers: 单花 / 两花各归一方
    "cf617c": ["1 0 0 1 1\n2 2", "2 0 0 10 0\n1 0\n0 1"],
    # 912B New Year's Eve: k=1 / k=n / 上界
    "cf912b": ["1 1", "1000000000000000000 1", "2 2", "1000000000000000000 1000000000000000000"],
    # 1486B Eastern Exhibition: n=1 / 两点 / 重合点
    "cf1486b": ["1\n1\n0 0", "1\n2\n0 0\n1000000000 1000000000", "1\n3\n0 0\n0 0\n0 0"],
    # 510B Fox And Two Dots: 最小 2x2 / 全同
    "cf510b": ["2 2\nAA\nAA", "2 2\nAB\nBA", "3 3\nAAA\nABA\nAAA"],
    # 1249E By Elevator or Stairs: n=2 最小 / c 上界 / 三步
    "cf1249e": ["2 1\n1\n1", "2 1000\n1000\n1000", "3 1\n1 1\n1 1"],
    # 106E Space Rescuers: n=1 / 对角极值
    "cf106e": ["1\n0 0 0", "2\n-10000 -10000 -10000\n10000 10000 10000"],
    # 1271A Suits: 全 1 / 全上界
    "cf1271a": ["1\n1\n1\n1\n1\n1", "100000\n100000\n100000\n100000\n1000\n1000"],
    # 719A Vitya in the Countryside: n=1 两端 / 上升下降
    "cf719a": ["1\n0", "1\n15", "2\n0 1", "2\n15 14"],
    # 1956D Nene and the Mex Operator: n=1 / n 上界
    "cf1956d": ["1\n0", "18\n" + "10000000 " * 17 + "10000000"],
    # 105B Dark Assembly: n=k=1 / n=8 全档
    "cf105b": [
        "1 1 1\n1 0",
        "8 8 9999\n9999 100\n1 0\n1 10\n1 20\n1 30\n1 40\n1 50\n1 60\n1 70",
    ],
    # 1216F Wi-Fi: 无路由位 / 全可放
    "cf1216f": ["1 1\n1", "1 1\n0", "3 1\n111"],
    # 1130C Connect: 1x1 / 2x2 全陆
    "cf1130c": ["1\n1 1\n1 1\n0", "2\n1 1\n2 2\n00\n00"],
    # 2000D Right Left Wrong: n=2 LR / RL
    "cf2000d": ["1\n2\n1 1\nLR", "1\n2\n100000 100000\nRL"],
    # 493B Vasya and Wrestling: 单方 / 平局
    "cf493b": ["1\n1", "1\n-1", "2\n1\n-1", "2\n1000000000\n-1000000000"],
    # 744A Hongcow Builds A Nation: 无路 / 星形
    "cf744a": ["1 0 1\n1", "3 0 1\n2", "3 2 1\n2\n1 2\n2 3"],
    # 1598A Computer Game: 最小 n / 全陷阱
    "cf1598a": ["1\n3\n000\n000", "1\n3\n010\n101"],
    # 1392F Omkar and Landslide: n=1 / 紧邻
    "cf1392f": ["1\n0", "2\n0 1", "3\n0 1 2"],
    # 75E Ship's Shortest Path: 起点终点在外侧
    "cf75e": ["0 -100 0 100\n4\n-10 -10 -10 10 10 10 10 -10", "-100 0 100 0\n4\n-10 -10 -10 10 10 10 10 -10"],
    # 380C Sereja and Brackets: 单查询 / 嵌套
    "cf380c": ["()\n1\n1 2", "((()))\n2\n1 6\n2 5"],
    # 282E Sausage Maximization: 单元素 / 全同极值
    "cf282e": ["1\n0", "2\n0 0", "3\n1000000000000 1000000000000 1000000000000"],
    # 2117E Lost Soul: n=2 相同/同值
    "cf2117e": ["1\n2\n1 2\n1 2", "1\n2\n1 1\n1 1"],
    # 1351C Skier: 单位移 / 往返
    "cf1351c": ["1\nS", "1\nNS", "2\nNNN\nSSS"],
    # 584B Kolya and Tanya: n=1,2 已有 → 3 / 上界
    "cf584b": ["3", "100000", "5"],
    # 117A Elevator: 单乘客 / s>f 反向 / 上界
    "cf117a": ["1 2\n1 2 0", "2 100000000\n1 100000000 100000000\n100000000 1 0"],
    # 258B Little Elephant and Elections: 下界 / 上界
    "cf258b": ["7", "1000000000"],
    # 1971H ±1: n=2 最小 / 反号
    "cf1971h": ["1\n2\n1 2\n-1 -2\n2 -2", "1\n2\n1 -1\n1 -1\n1 -1"],
    # 325A Square and Rectangles: 单位方格 / 满坐标
    "cf325a": ["1\n0 0 1 1", "1\n0 0 31400 31400"],
    # 1196D2 RGB Substring: n=k=1 / 全同 / 子串=2
    "cf1196d2": ["1\n1 1\nR", "1\n3 3\nRGB", "1\n3 2\nBBB"],
    # 146B Lucky Mask: 相邻 / b 上界幸运数
    "cf146b": ["1 4", "100000 4", "100000 44444"],
    # 327C Magic Five: 单字符 k=1 / 全零 k 上界
    "cf327c": ["1\n1", "0\n1000000000", "55\n1000000000"],
    # 444A DZY Loves Physics: 无边 / 双点一边
    "cf444a": ["1 0\n1000000", "2 1\n1000000 1000000\n1 2 1000"],
    # 895C Square Subsets: 单元素 1 / 70 / 重复
    "cf895c": ["1\n1", "1\n70", "2\n70 70"],
    # 1717B Madoka and Underground Competitions: n=k=1 / n=4,k=2
    "cf1717b": ["1\n1 1 1 1", "1\n4 2 3 1"],
    # 1260A Heating: 全 1 / 全上界 / c=1,s 大
    "cf1260a": ["1\n1 1", "1\n10000 10000", "1\n1 10000"],
    # 1139D Steps to One: m=3 / 上界
    "cf1139d": ["3", "100000"],
    # 71D Solitaire: 最小 3x3 同花顺
    "cf71d": ["3 3\n2S 3S 4S\n5S 6S 7S\n8S 9S TS"],
    # 1166E LCMs Must be Large: 单日 / 双日互补
    "cf1166e": ["1 2\n1 1", "1 2\n1 2", "2 3\n1 1\n1 3"],
    # 1641C Anonymity Is Important: 最简 / 条件+查询
    "cf1641c": ["1 1\n1 1", "1 2\n0 1 1 0\n1 1"],
    # 230B T-primes: 1 / 上界 / 重复平方数
    "cf230b": ["1\n1", "1\n1000000000000", "2\n4 4"],
    # 1929B Sasha and the Drawing: k 最小 / 满对角 / n 上界
    "cf1929b": ["1\n2 1", "1\n2 6", "1\n100000000 399999998"],
    # 1169A Circle Metro: n=4 两排布
    "cf1169a": ["4 1 2 3 4", "4 1 4 2 3"],
    # 1305E Kuroni and the Score Distribution: m 最小 / 满 n（special）
    "cf1305e": ["1 0", "1 1", "5000 0", "5000 1000000000"],
    # 844A Diversity: 单字符 / 全字母 / 不可行
    "cf844a": ["a\n1", "a\n26", "abcdefghijklmnopqrstuvwxyz\n26"],
    # 513B2 Permutations(hard): n=1 / n=50
    "cf513b2": ["1 1", "50 1"],
    # 69D Dot: d=1 / 大向量
    "cf69d": ["0 0 1 1\n1 0", "0 0 1 200\n200 0"],
    # 960D Full Binary Tree Queries: 单查询 / 旋转+查询
    "cf960d": ["1\n3 1", "2\n1 1 0\n3 1"],
    # 825C Multi-judge Solving: 单题 / 上界
    "cf825c": ["1 1\n1", "1 1000000000\n1000000000"],
    # 332A Down the Hatch!: 单回合 a / b / 长串
    "cf332a": ["4\na", "4\nb", "4\nabbbba"],
    # 49B Sum: 单边 / 双边上界
    "cf49b": ["1 1000", "1000 1", "1000 1000"],
    # 1974C Beautiful Triple Pairs: n=3 全同 / 全异
    "cf1974c": ["1\n3\n1 1 1", "1\n3\n1 2 3"],
    # 1179A Valeriy and Deque: q=1 / 大 m
    "cf1179a": ["2 1\n1 2\n1", "2 2\n1 1\n1000000000000000000\n1"],
    # 1054C Candies Distribution: n=1 / 两孩全零（special）
    "cf1054c": ["1\n0\n0", "1\n1\n1", "2\n0 0\n0 0"],
    # 859B Lazy Security Guard: 最小 / 上界
    "cf859b": ["1", "1000000", "2"],
    # 1485F Copy or Prefix Sum: 单元素 正/负/零
    "cf1485f": ["1\n1\n0", "1\n1\n1000000000", "1\n1\n-1000000000"],
    # 1077E Thematic Contests: 单题 / 同题 / 三种
    "cf1077e": ["1\n1", "2\n1 1", "3\n1 1 1"],
    # 2121H Ice Baby: 单区间 / 两区间极值
    "cf2121h": ["1\n1\n1 1", "1\n2\n1 1\n1 1000000000"],
    # 1443E Long Permutation: 单查询 / 旋转+查询
    "cf1443e": ["2 1\n1 1 1", "2 2\n1 1 2\n2 1"],
    # 1327C Game with Chips: 2x2 单芯片 / 3x3 单芯片（special）
    "cf1327c": ["2 2 1\n1 1\n2 2", "3 3 1\n1 1\n3 3"],
    # 1185C2 Exam in BerSU: 单学生 / 全满时
    "cf1185c2": ["1 1\n1", "2 100\n100 100"],
    # 54A Presents: 无假日 / 全假日 / 部分假日
    "cf54a": ["1 1\n0", "365 365\n0", "365 1\n3 1 2 3"],
    # 312B Archer: 全 1 / 极小概率
    "cf312b": ["1 1 1 1", "1 100 1 100"],
    # 1612C Chat Ban: k=1 / 上界
    "cf1612c": ["1\n1 1", "1\n1000000000 1000000000000000000"],
    # 1391C Cyclic Permutations: n=3 / 上界
    "cf1391c": ["3", "1000000"],
    # 1062A A Prank: 单元素 / 相邻 / 上界
    "cf1062a": ["1\n1", "1\n1000", "2\n1 2"],
    # 352A Jeff and Digits: 单 0 / 单 5 / 九个 5
    "cf352a": ["1\n0", "1\n5", "9\n5 5 5 5 5 5 5 5 5"],
    # 1334E Divisor Paths: D=1 / D=2
    "cf1334e": ["1\n1\n1 1", "2\n1\n2 1"],
    # 1918D Blocking Elements: 单元素 / 上界
    "cf1918d": ["1\n1\n1", "1\n1\n1000000000"],
    # 1798E Multitest Generator: n=2 两态
    "cf1798e": ["1\n2\n1 1", "1\n2\n1 2"],
    # 500B New Year Permutation: n=1 / 可交换对
    "cf500b": ["1\n1\n0", "2\n2 1\n01\n10"],
    # 1593E Gardener and Tree: 单点 / 两点 / 大 k
    "cf1593e": ["1\n\n1 1", "1\n\n2 1\n1 2", "1\n\n2 200000\n1 2"],
    # 2230C Arrange the Numbers in a Circle: 单元素 / 重复
    "cf2230c": ["1\n1\n1", "1\n1\n1000000000", "1\n2\n1 1"],
    # 371C Hamburgers: 单料 r=0 / 大 r
    "cf371c": ["B\n1 1 1\n1 1 1\n0", "S\n1 1 1\n1 1 1\n1000000000000"],
    # 1253B Silly Mistake: 单人入 / 出入 / 一对（special）
    "cf1253b": ["1\n1", "1\n-1", "2\n1 -1"],
    # 27B Tournament: 缺两场之一（special）
    "cf27b": ["3\n1 2\n1 3", "3\n2 1\n3 1"],
    # 915C Permute Digits: 单位数 / 相同
    "cf915c": ["1\n1", "9\n9"],
    # 810A Straight: 单科满分 / 双科满分
    "cf810a": ["1 1\n1", "2 100\n100 100"],
    # 622D Optimal Number Permutation: 最小 / 上界
    "cf622d": ["1", "2", "500000"],
    # 1739E Cleaning Robot: 全净 / 一格脏
    "cf1739e": ["2\n00\n00", "2\n00\n01"],
    # 459C Pashmak and Buses: 最小 / 上界
    "cf459c": ["1 1 1", "2 1 1", "1000 1000000000 1000"],
    # 1696D Permutation Graph: n=1 / 升序 / 降序
    "cf1696d": ["1\n1\n1", "1\n2\n1 2", "1\n2\n2 1"],
    # 1520E Arranging The Sheep: 单格空 / 单格羊 / 两格
    "cf1520e": ["1\n1\n.", "1\n1\n*", "1\n2\n.*"],
    # 1257D Yet Another Monster Killing: 单怪单英 / 上界
    "cf1257d": ["1\n1\n1\n1\n1 1", "1\n1\n1000000000\n1\n1000000000 1"],
    # 1991C Absolute Zero: 单元素 0 / 上界（special）
    "cf1991c": ["1\n1\n0", "1\n1\n1000000000"],
    # 568A Primes or Palindromes: p/q ≤ 1 三态
    "cf568a": ["1 1", "1 2", "3 2"],
    # 44B Cola: 单升 / 全上界
    "cf44b": ["1 0 0 0", "10000 5000 5000 5000"],
    # 1042B Vitamins: 单维生素 / 全维生素 / 大价
    "cf1042b": ["1\n1 A", "1\n1 ABC", "1\n100000 ABC"],
    # 1272A Three Friends: 三点重合 / 两端
    "cf1272a": ["1\n1 1 1", "1\n1000000000 1 1000000000"],
    # 1230B Ania and Minimizing: 不改 / 改满 / 两位
    "cf1230b": ["1 0\n1", "1 1\n1", "2 1\n10"],
    # 20C Dijkstra?: m=0 / 单边（special）
    "cf20c": ["2 0", "2 1\n1 2 1"],
    # 1408D Searchlights: 同点 / 极值
    "cf1408d": ["1 1\n0 0\n0 0", "1 1\n1000000 1000000\n0 0"],
    # 915D Almost Acyclic Graph: 单向 / 双向环
    "cf915d": ["2 1\n1 2", "2 2\n1 2\n2 1"],
    # 53C Little Frog: 最小 / 偶数 / 上界（special）
    "cf53c": ["1", "4", "10000"],
    # 131C The World is a Theatre: 边界组合 4+1 / 满
    "cf131c": ["4 1 5", "30 30 60"],
    # 792D Paths in Complete Binary Tree: n=1 / n=3 / n=7
    "cf792d": ["1 1\n1\nU", "3 1\n1\nU", "7 2\n1\nL\n7\nU"],
    # 597B Restaurant: 单订单 / 相邻
    "cf597b": ["1\n1 1", "2\n1 2\n2 3"],
    # 645B Mischievous Mess Makers: 单牛 / 上界
    "cf645b": ["1 1", "100000 100000"],
    # 682B Alyona and Mex: 单元素 / 上界 / 两位
    "cf682b": ["1\n1", "1\n1000000000", "2\n1 2"],
    # 352B Jeff and Periods: 单元素 / 上界值 / 相邻对
    "cf352b": ["1\n1", "1\n100000", "2\n1 1"],
    # 437B The Child and Set: 最小 / 上界 / 不可行（special）
    "cf437b": ["1 1", "100000 100000", "100000 1"],
    # 991C Candies: n=1 / 上界
    "cf991c": ["1", "1000000000000000000"],
    # 166E Tetrahedron: n=1 / 上界
    "cf166e": ["1", "10000000"],
    # 292B Network Topology: 星形 / 链式
    "cf292b": ["4 3\n2 1\n2 3\n2 4", "5 4\n1 2\n2 3\n3 4\n4 5"],
    # 384A Coder: 1 / 3 / 4（special）
    "cf384a": ["1", "3", "4"],
    # 437C The Child and Toy: 无边 / 单边
    "cf437c": ["1 0\n1", "2 1\n1 2\n1 2"],
    # 1102C Doors Breaking and Repairing: 单门最小 / 全上界
    "cf1102c": ["1 1 1\n1", "1 100000 100000\n100000"],
    # 15C Industrial Nim: 最小 / x,m 上界
    "cf15c": ["1\n1 1", "1\n10000000000000000 1"],
    # 707B Bakery: 单边有仓 / k=0 无仓
    "cf707b": ["4 1 1\n1 2 5\n3", "2 1 0\n1 2 1"],
    # 1250A Berstagram: 单帖单赞 / 同帖重复赞
    "cf1250a": ["1 1\n1", "1 2\n1 1"],
    # 61D Eternal Victory: 单城 / 零权边
    "cf61d": ["1", "2\n1 2 0"],
    # 755B PolandBall and Game: 无交集 / 有交集
    "cf755b": ["1 1\na\nb", "1 1\na\na"],
    # 347A Difference Row: 两点相同 / 升序
    "cf347a": ["2\n0 0", "3\n1 2 3"],
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
                failed.append(f"{sid}: 输入 {inp!r} 运行失败: {err[:100]}")
                continue
            new_cases.append({"input": inp, "output": out, "hidden": True})
        if new_cases:
            r["test_cases"].extend(new_cases)
            added += len(new_cases)
            print(f"{r['id']} {sid}: +{len(new_cases)} 隐藏用例")
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"\n共新增 {added} 个隐藏用例")
    if failed:
        print("失败项（输入可能不合格式，已跳过）：")
        for f in failed:
            print(" ", f)


if __name__ == "__main__":
    main()

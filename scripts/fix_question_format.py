"""一次性脚本：修正 A1002/A1003 的题面格式（英文保留，LaTeX 符号转可读文本，结构清晰）。"""
import json
from pathlib import Path

F = Path(__file__).resolve().parents[1] / "data" / "questions" / "abc_selfbuilt.jsonl"

A1002_PROMPT = """Score : 200 points

### Problem Statement
AtCoder Kingdom uses a calendar whose year has N months.
Month i (1 ≤ i ≤ N) has D_i days, from day 1 of month i to day D_i of month i.

How many days in a year of AtCoder have "repdigits" dates?
Here, day j of month i (1 ≤ i ≤ N, 1 ≤ j ≤ D_i) is said to have a repdigit date
if and only if all digits in the decimal notations of i and j are the same.

### Constraints
- 1 ≤ N ≤ 100
- 1 ≤ D_i ≤ 100 (1 ≤ i ≤ N)
- All input values are integers.

### Input
The input is given from Standard Input in the following format:

N
D_1 D_2 ... D_N

### Output
Print the answer.

### Sample Input 1
12
31 29 31 30 31 30 31 31 30 31 30 31

### Sample Output 1
13

In AtCoder Kingdom, the days that have repdigit dates are January 1, January 11,
February 2, February 22, March 3, April 4, May 5, June 6, July 7, August 8,
September 9, November 1, and November 11, for a total of 13 days.

### Sample Input 2
10
10 1 2 3 4 5 6 7 8 100

### Sample Output 2
1

In AtCoder Kingdom, only January 1 has a repdigit date.

### Sample Input 3
30
73 8 55 26 97 48 37 47 35 55 5 17 62 2 60 23 99 73 34 75 7 46 82 84 29 41 32 31 52 32

### Sample Output 3
15
"""

A1003_PROMPT = """Score : 100 points

### Problem Statement
You will be given a string S of length 3 representing the weather forecast for
three days in the past. The i-th character (1 ≤ i ≤ 3) of S represents the
forecast for the i-th day. S, C, and R stand for sunny, cloudy, and rainy,
respectively.

You will also be given a string T of length 3 representing the actual weather
on those three days. The i-th character (1 ≤ i ≤ 3) of T represents the actual
weather on the i-th day. S, C, and R stand for sunny, cloudy, and rainy,
respectively.

Print the number of days for which the forecast was correct.

### Constraints
- S and T are strings of length 3 each.
- S and T consist of S, C, and R.

### Input
Input is given from Standard Input in the following format:

S
T

### Output
Print the number of days for which the forecast was correct.

### Sample Input 1
CSS
CSR

### Sample Output 1
2

For the first day, it was forecast to be cloudy, and it was indeed cloudy.
For the second day, it was forecast to be sunny, and it was indeed sunny.
For the third day, it was forecast to be sunny, but it was rainy.
Thus, the forecast was correct for two days in this case.

### Sample Input 2
SSR
SSR

### Sample Output 2
3

### Sample Input 3
RRR
SSS

### Sample Output 3
0
"""

PROMPTS = {"A1002": A1002_PROMPT, "A1003": A1003_PROMPT}


def main() -> None:
    recs = [json.loads(l) for l in F.open(encoding="utf-8") if l.strip()]
    updated = 0
    for q in recs:
        if q["id"] in PROMPTS:
            q["prompt"] = PROMPTS[q["id"]]
            updated += 1
    F.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in recs),
                 encoding="utf-8")
    print(f"updated {updated} prompts")


if __name__ == "__main__":
    main()

"""一次性脚本：重写 A1001/A1002/A1003 参考解为清晰可读版（保留 AC 解核心逻辑，去冗余模板）。

重写后需核对：与原版 AC 解对全部输入样例输出一致（见 verify 步骤）。
"""
import json
from pathlib import Path

F = Path(__file__).resolve().parents[1] / "data" / "questions" / "abc_selfbuilt.jsonl"

# A1001 ABC161 D - Lunlun 数：DFS 生成所有 Lunlun 数，排序取第 K
A1001_REF = """#include <bits/stdc++.h>
using namespace std;
typedef long long ll;

int main() {
    vector<ll> v;
    // DFS 生成所有 Lunlun 数（任意相邻数字差 ≤1，最长 10 位）
    function<void(int, ll)> dfs = [&](int k, ll x) {
        v.push_back(x);
        if (k >= 9) return;                 // 已达 10 位，停止
        int a = x % 10;
        if (a)     dfs(k + 1, x * 10 + a - 1);  // 末位减 1
        dfs(k + 1, x * 10 + a);                 // 末位不变
        if (a < 9) dfs(k + 1, x * 10 + a + 1);  // 末位加 1
    };
    for (int d = 1; d <= 9; d++) dfs(0, d);     // 首位 1~9
    sort(v.begin(), v.end());
    v.erase(unique(v.begin(), v.end()), v.end());
    int K; cin >> K;
    cout << v[K - 1] << endl;
    return 0;
}
"""

# A1002 ABC328 B - repdigit 日期：遍历月/日，i 与 j 的数字去重后只有一种 → 计数
A1002_REF = """#include <bits/stdc++.h>
using namespace std;

int main() {
    int N; cin >> N;
    vector<int> D(N);
    for (int i = 0; i < N; i++) cin >> D[i];

    int ans = 0;
    for (int i = 1; i <= N; i++) {                  // 月份
        for (int j = 1; j <= D[i - 1]; j++) {       // 该月天数
            int x = i, y = j;
            set<int> digits;
            while (x) { digits.insert(x % 10); x /= 10; }
            while (y) { digits.insert(y % 10); y /= 10; }
            if (digits.size() == 1) ans++;          // 只用了一种数字
        }
    }
    cout << ans << endl;
    return 0;
}
"""

# A1003 ABC139 A - Tenki：比较 S 与 T 相同位置字符
A1003_REF = """#include <bits/stdc++.h>
using namespace std;

int main() {
    string S, T;
    cin >> S >> T;
    int cnt = 0;
    for (int i = 0; i < 3; i++) {
        if (S[i] == T[i]) cnt++;
    }
    cout << cnt << endl;
    return 0;
}
"""

REFS = {"A1001": A1001_REF, "A1002": A1002_REF, "A1003": A1003_REF}


def main() -> None:
    recs = [json.loads(l) for l in F.open(encoding="utf-8") if l.strip()]
    updated = 0
    for q in recs:
        if q["id"] in REFS:
            q["reference_solution"] = REFS[q["id"]]
            updated += 1
    F.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in recs),
                 encoding="utf-8")
    print(f"rewrote {updated} reference solutions")


if __name__ == "__main__":
    main()

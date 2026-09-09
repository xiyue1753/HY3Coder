// SPJ checker for AtCoder ABC251_D "At Most 3 (Contestant ver.)".
// 判定：给定 W，输出 N 个砝码 A_i（1<=N<=300, 1<=A_i<=1e6，允许重复），
// 使 [1,W] 内每个整数都可用至多 3 个（含等值砝码）表示。
//
// stdin 协议（见 rex/executor/judge.py）：
//   第一段 原题输入 W\n
//   @@REX_USER_OUTPUT@@\n
//   第二段 被测输出（N\nA1..AN\n）
// 输出 "AC" 或 "WA: 原因"。
#include <bits/stdc++.h>
using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    string all;
    string line;
    while (getline(cin, line)) all += line + "\n";

    const string sep = "@@REX_USER_OUTPUT@@";
    size_t pos = all.find(sep);
    if (pos == string::npos) { cout << "WA: 缺分隔符\n"; return 0; }
    string head = all.substr(0, pos);
    string tail = all.substr(pos + sep.size());

    long long W = -1;
    {
        istringstream hs(head);
        hs >> W;
    }
    if (W < 1 || W > 1000000) { cout << "WA: W 越界\n"; return 0; }

    vector<long long> A;
    {
        istringstream ts(tail);
        int N = -1;
        ts >> N;
        if (N < 1 || N > 300) { cout << "WA: N=" << N << " 不在 [1,300]\n"; return 0; }
        long long x;
        for (int i = 0; i < N; i++) {
            if (!(ts >> x)) { cout << "WA: 砝码数量不足\n"; return 0; }
            if (x < 1 || x > 1000000) { cout << "WA: 砝码质量越界\n"; return 0; }
            A.push_back(x);
        }
    }

    // u1: 单砝码和；u2: 两砝码和（保序稀疏列表）；u3 由 u2 平移得到
    vector<char> u2(2000001, 0), u3(3000001, 0);
    vector<int> two;
    for (size_t i = 0; i < A.size(); i++) {
        if (A[i] <= W) u3[A[i]] = 1;  // 单砝码先并入 u3 候选
    }
    for (size_t i = 0; i < A.size(); i++) {
        for (size_t j = 0; j < A.size(); j++) {
            if (i == j) continue;  // "不同砝码"：同一砝码不得使用两次
            long long s = A[i] + A[j];
            if (s <= 2000000 && !u2[s]) {
                u2[s] = 1;
                two.push_back((int)s);
            }
        }
    }
    for (size_t i = 0; i < A.size(); i++) {
        for (int s : two) {
            long long v = A[i] + s;
            if (v <= 3000000) u3[v] = 1;
        }
    }
    for (long long t = 1; t <= W; t++) {
        bool ok = (t <= 2000000 && u2[t]) || (t <= 3000000 && u3[t]);
        if (!ok) { cout << "WA: " << t << " 无法用<=3个砝码表示\n"; return 0; }
    }
    cout << "AC\n";
    return 0;
}

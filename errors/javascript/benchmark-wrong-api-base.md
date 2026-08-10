---
title: "ベンチマークを Go バックエンド経由で呼ぶと python_ms が undefined になる"
tags: [javascript, fetch, benchmark, frontend]
severity: high
date: "2026-08-09"
---

## 症状

バックエンドを Go に切り替えた状態でベンチマークを実行すると、
棒グラフの Python 側が NaN / 幅ゼロになる。コンソールに警告なし。

## 原因

`fetchBenchmark()` が `${apiBase}/api/benchmark` を呼んでいた。
Go の `/api/benchmark` は `{url, type, go_ms}` のみ返す（`python_ms` なし）。
`Math.max(undefined, ...)` が NaN になる。

## 解決策

```javascript
// ❌ Before
const res = await fetch(`${apiBase}/api/benchmark?url=${...}`);

// ✅ After — ベンチマークは常に Python ('' = root) を呼ぶ
const res = await fetch(`/api/benchmark?url=${...}`);
```

Python の `/api/benchmark` が内部で Go を計測するため、
ユーザーが Go モードでも Python エンドポイントを使う設計が正しい。

## 予防

バックエンドトグルを追加する際、各エンドポイントが「Python 限定」か「両方で動く」かを
最初に整理してから `apiBase` を使うか直書きするかを決める。

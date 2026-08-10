---
title: "Render で異なる GitHub アカウントのリポジトリに接続できない"
tags: [render, github, deployment]
severity: medium
date: "2026-08-08"
---

## 症状

Render の YukiLabs ワークスペース（`yukilabs-core` GitHub アカウント接続済み）から
`flipslidersand` アカウントのリポジトリを Blueprint で接続しようとしても
リポジトリ一覧に表示されない。GitHub App のインストール画面で `flipslidersand` を
選択・Save しても Render 側に反映されない。

## 原因

Render ワークスペースは作成時に紐付けた GitHub アカウント（org）に対してのみ
GitHub App がインストールされる。別アカウントのリポジトリは同一ワークスペースから
直接接続できない（Render の仕様）。

## 解決策

`flipslidersand` GitHub アカウントで **新規 Render アカウント** を作成し、
そちらで Blueprint を接続する。

```
1. render.com で新規サインアップ（flipslidersand GitHub でログイン）
2. New → Blueprint → flipslidersand/github-engineer-dashboard を選択
3. 環境変数（GITHUB_TOKEN / CORS_ORIGINS）を設定して Deploy
```

## 予防

- Render ワークスペースと GitHub アカウントは 1:1 対応
- `yukilabs-core` 用と `flipslidersand` 用でそれぞれ Render アカウントを分けて管理する
- `render.yaml` の `name` フィールドが Render 上のサービス名になる（重複に注意）

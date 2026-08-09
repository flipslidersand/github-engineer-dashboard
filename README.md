# github-engineer-dashboard

GitHub API で任意の URL（ユーザー / リポジトリ / PR / Issue）を分析・可視化するダッシュボード。  
Python (FastAPI) と Go の 2 バックエンドを搭載し、レイテンシを直接比較できる。

## デモ

> **録画手順**: [docs/recording-guide.md](docs/recording-guide.md)

![demo](docs/demo.gif)

<!-- demo.gif が未作成の場合は上の行を削除し、以下を残す
録画後に docs/demo.gif を追加してください。
-->

| サービス           | URL                                                |
| ------------------ | -------------------------------------------------- |
| Python 版 (Render) | https://github-engineer-dashboard-api.onrender.com |
| Go 版 (Render)     | https://github-engineer-dashboard-go.onrender.com  |

> Render free tier のため初回アクセスは Cold start（約 50s）あり。

## 機能

| タブ             | 説明                                                                     |
| ---------------- | ------------------------------------------------------------------------ |
| **Analyze**      | GitHub URL を入力するだけで User / Repo / PR / Issue を自動判定して分析  |
| **Summary**      | ユーザー・組織の全リポジトリを集計（スター合計・言語分布・フォーク数）   |
| **Compare**      | User 同士・Repo 同士を横並び比較                                         |
| **⚡ Benchmark** | Python vs Go のレスポンス速度を CSS バーグラフで可視化、履歴テーブル付き |

- ヘッダのトグル（**Backend: Python \| Go ⚡**）でバックエンドを切り替え
- PR 分析画面から **AI Review** ボタンで Claude / Ollama による diff レビューを実行
- SQLite TTL キャッシュ（300s）でレート制限を回避

## 技術スタック

| レイヤー     | 技術                                                 |
| ------------ | ---------------------------------------------------- |
| API (Python) | Python 3.12 / FastAPI / Uvicorn                      |
| API (Go)     | Go 1.25 / chi / modernc.org/sqlite                   |
| キャッシュ   | SQLite (TTL 300s、各バックエンドで独立)              |
| フロント     | Vanilla HTML + CSS + Fetch API                       |
| AI Review    | Claude Haiku (`ANTHROPIC_API_KEY`) / Ollama fallback |
| デプロイ     | Render (`render.yaml` Blueprint)                     |
| テスト       | pytest (35 tests)                                    |

## エンドポイント

### 共通（Python / Go 両方）

| Method | Path                             | 説明                                   |
| ------ | -------------------------------- | -------------------------------------- |
| GET    | `/healthz`                       | Liveness（認証不要）                   |
| GET    | `/api/rate-limit`                | GitHub rate-limit 残量                 |
| GET    | `/api/analyze?url=`              | URL 自動判定分析（user/repo/pr/issue） |
| GET    | `/api/summary?url=`              | ユーザー・組織集計                     |
| GET    | `/api/users/{username}/activity` | ユーザーアクティビティ詳細             |
| GET    | `/api/benchmark?url=`            | Go レイテンシ計測                      |

### Python のみ

| Method | Path                  | 説明                                   |
| ------ | --------------------- | -------------------------------------- |
| GET    | `/`                   | フロント UI 配信                       |
| GET    | `/api/config`         | Go バックエンド URL 通知（フロント用） |
| GET    | `/api/review?url=`    | AI diff レビュー（PR URL のみ）        |
| GET    | `/api/benchmark?url=` | Python + Go 両方を計測して比較         |

### 認証

すべての `/api/*` は `X-GitHub-Token` ヘッダまたは `GITHUB_TOKEN` 環境変数を参照。  
Fine-grained PAT（public repos: read）で OK。

## ローカル開発

```bash
# Python バックエンド
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GITHUB_TOKEN=ghp_xxx
uvicorn app.main:app --reload --port 8000
# → http://localhost:8000

# Go バックエンド（別ターミナル）
cd backend-go
go build -o server . && GITHUB_TOKEN=$GITHUB_TOKEN ./server
# → http://localhost:8080

# Go を Python から参照する場合
export GO_BACKEND_URL=http://localhost:8080

# テスト
pytest -q
```

OpenAPI ドキュメント: `http://localhost:8000/docs`

## デプロイ（Render）

`render.yaml` に Python + Go の両サービスを定義済み。

```
Render Dashboard → New → Blueprint → このリポジトリを選択
```

**初回のみ Render Dashboard で設定する環境変数:**

| サービス | 変数             | 説明                    |
| -------- | ---------------- | ----------------------- |
| Python   | `GITHUB_TOKEN`   | Fine-grained PAT        |
| Python   | `CORS_ORIGINS`   | 自動設定（fromService） |
| Python   | `GO_BACKEND_URL` | 自動設定（fromService） |
| Go       | `GITHUB_TOKEN`   | Fine-grained PAT        |
| Go       | `CORS_ORIGINS`   | 自動設定（fromService） |

`fromService` により、両サービスのデプロイ後に URL が自動注入される。

## リポジトリ構成

```
app/
  main.py           FastAPI アプリ + 全ルート
  config.py         環境変数 → Settings
  github_client.py  GitHub REST クライアント（並列取得）
  cache.py          SQLite TTL キャッシュ
  models.py         Pydantic モデル（Go 版との共有契約）
  reviewer.py       AI diff レビュー（Claude / Ollama）
  url_parser.py     GitHub URL パーサー
  static/
    index.html      Vanilla HTML ダッシュボード
backend-go/
  main.go                     エントリポイント + CORS ミドルウェア
  internal/cache/             SQLite TTL キャッシュ（Go）
  internal/github/client.go   GitHub REST クライアント（並列取得）
  internal/handler/routes.go  ルート登録 + fromCache ジェネリクスヘルパー
  internal/model/types.go     レスポンス型（Python 版と一致）
docs/
  recording-guide.md  デモ GIF 録画手順
tests/              pytest スイート（35 tests）
render.yaml         Render Blueprint（Python + Go 両サービス）
```

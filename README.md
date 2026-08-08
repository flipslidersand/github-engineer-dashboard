# github-engineer-dashboard

GitHub API で任意ユーザーの開発アクティビティを可視化するダッシュボード。

- **Phase 1** — Python / FastAPI バックエンド + vanilla HTML フロント
- **Phase 2** — 同一 OpenAPI 契約を Go で再実装し、レイテンシを比較 (WIP)

## デモ

|           | URL                              | 状態   |
| --------- | -------------------------------- | ------ |
| Python 版 | TBD (Render deploy #63 後に追記) | 準備中 |
| Go 版     | TBD (Phase 2 完成後)             | 未実装 |

## 技術スタック

| レイヤー       | 技術                            |
| -------------- | ------------------------------- |
| API (Phase 1)  | Python 3.12 / FastAPI / Uvicorn |
| API (Phase 2)  | Go 1.22 / net/http              |
| キャッシュ     | SQLite (TTL 300s)               |
| フロントエンド | vanilla HTML + CSS + Fetch API  |
| デプロイ       | Render (render.yaml)            |
| テスト         | pytest                          |

## パフォーマンス比較 (Phase 2 完成後に更新)

| 実装             | p50 レイテンシ | p99 レイテンシ | メモリ |
| ---------------- | -------------- | -------------- | ------ |
| Python (FastAPI) | - ms           | - ms           | - MB   |
| Go (net/http)    | - ms           | - ms           | - MB   |

> ベンチマーク: `wrk -t4 -c100 -d30s http://localhost:8000/api/users/torvalds/activity`

## エンドポイント

- `GET /` — フロント UI 配信（`static/index.html`）
- `GET /static/*` — 静的アセット配信
- `GET /healthz` — liveness (認証不要)
- `GET /api/rate-limit` — GitHub rate-limit 残量
- `GET /api/analyze?url=` — GitHub URL 分析（user / repo 自動判定、キャッシュ付き）
- `GET /api/users/{username}/activity` — プロフィール + 直近イベントサマリー（SQLite キャッシュ付き）

### 認証

GitHub API の rate limit は未認証で 60 req/h、PAT で 5000 req/h。  
サーバー側に Fine-grained PAT を設定（ユーザーにトークン入力は不要）。

```bash
# Render Dashboard または .env で設定
GITHUB_TOKEN=ghp_xxxxxxxxxxxx   # Fine-grained PAT (public_repos: read-only)
```

### レート制限対策

- SQLite に TTL 300s でキャッシュ → rate limit 枯渇時も画面が止まらない
- `/api/rate-limit` で残量をリアルタイム表示（キャッシュなし）

## 開発

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# ローカル起動
export GITHUB_TOKEN=ghp_xxx
uvicorn app.main:app --reload

# フロントエンド: static/index.html をブラウザで開く

# テスト
pytest -q
```

OpenAPI ドキュメント: 起動後 `http://localhost:8000/docs`

## デプロイ

`render.yaml` を同梱。Render > New Blueprint で読み込むと Python Web Service が作られる。

環境変数（Render Dashboard で設定、平文コミット禁止）:

| 変数           | 説明                                                |
| -------------- | --------------------------------------------------- |
| `GITHUB_TOKEN` | Fine-grained PAT (public repos read-only)           |
| `CORS_ORIGINS` | フロントエンドの Origin (例: `https://example.com`) |

ヘルスチェック: `GET /healthz`

## 構成

```text
app/
  main.py           FastAPI アプリ + ルート
  config.py         環境変数 → Settings
  github_client.py  GitHub REST クライアント
  cache.py          SQLite TTL キャッシュ
  models.py         Pydantic レスポンスモデル（Go 版との共有契約）
static/
  index.html        vanilla HTML ダッシュボード
tests/              pytest スイート
api.yaml            OpenAPI spec（Phase 2 Go 版のバリデーション基準）
render.yaml         Render デプロイ定義
```

## API 契約

[`api.yaml`](./api.yaml) が正とする OpenAPI spec。Phase 2 の Go 版はこの spec に対してバリデーションし、エンドポイント / レスポンス形式のズレを防ぐ。

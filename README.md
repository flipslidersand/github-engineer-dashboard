# github-engineer-dashboard

Developer activity dashboard backed by the GitHub API. Phase 1 is a Python /
FastAPI service; Phase 2 re-implements the same OpenAPI contract in Go for a
performance benchmark.

## Phase 1 (this scaffold)

- `GET /` — フロント UI 配信（`static/index.html`）。`STATIC_DIR` 未設定時はスキップ (Issue #55)
- `GET /static/*` — 静的アセット配信（`STATIC_DIR` 設定時のみ有効）
- `GET /healthz` — liveness (public)
- `GET /api/rate-limit` — live GitHub rate-limit quota (Issue #1)
- `GET /api/users/{username}/activity` — profile + recent public-event summary, cached

### 認証 (Issue #1)

`/api/*` は GitHub トークンが必須。以下のいずれかで渡す:

- リクエストヘッダー `X-GitHub-Token: <token>`（推奨・UI から入力）
- 環境変数 `GITHUB_TOKEN`（サーバー全体の既定）

トークンを使うことで rate limit が 60 → 5000 req/h に上がり、アクセス制御も兼ねる。

### レート制限対策 (Issue #1)

- レスポンスを SQLite にキャッシュ（TTL 既定 300 秒）→ 枯渇時もキャッシュで画面が止まらない
- `/api/rate-limit` で残量を可視化（キャッシュしない）

## 開発

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# ローカル起動
export GITHUB_TOKEN=ghp_xxx        # 任意（ヘッダーでも可）
uvicorn app.main:app --reload

# テスト
pytest -q
```

OpenAPI ドキュメント: 起動後 `http://localhost:8000/docs`。

## デプロイ (Issue #4)

`render.yaml` を同梱。Render で Blueprint として読み込むと Python web service が作られる。
`GITHUB_TOKEN` / `CORS_ORIGINS` は Render Dashboard で設定（平文コミット禁止）。
ヘルスチェック: `/healthz`。

## API 契約 (Issue #2)

[`api.yaml`](./api.yaml) が Python 版から生成した OpenAPI spec。Phase 2 の Go 版は
この spec に対してバリデーションし、エンドポイント/レスポンス形式のズレを防ぐ。

## 構成

```text
app/
  main.py           FastAPI アプリ + ルート + DI
  config.py         環境変数 → Settings
  github_client.py  GitHub REST クライアント
  cache.py          SQLite TTL キャッシュ
  models.py         Pydantic レスポンスモデル（共有契約）
tests/              cache / github_client / api のユニットテスト
api.yaml            生成された OpenAPI spec
render.yaml         Render デプロイ定義
```

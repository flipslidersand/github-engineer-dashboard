# アーキテクチャ概要とデータフロー

## システム構成

```
ブラウザ (index.html)
   │
   │  /api/config   (認証不要)
   │  /api/analyze  (X-GitHub-Token)
   │  /api/summary  ...
   ▼
Python バックエンド (FastAPI / Uvicorn)
   │
   ├── SQLite TTL キャッシュ (cache.db, 300s)
   │
   ├── GitHub REST API (v3)  ←── GITHUB_TOKEN 環境変数
   │
   └── Go バックエンド (オプション)
          │  /api/analyze, /api/benchmark
          ▼
       Go バックエンド (chi / modernc.org/sqlite)
          │
          ├── SQLite TTL キャッシュ (cache-go.db, 300s)
          └── GitHub REST API (v3)
```

## コンポーネント

| コンポーネント                          | 役割                                                                                             |
| --------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `app/static/index.html`                 | Vanilla HTML/CSS/JS の SPA。タブ切り替え、バックエンドトグル、ベンチマーク可視化                 |
| `app/main.py`                           | FastAPI アプリ。ルート定義・キャッシュ・GitHub クライアントの注入点                              |
| `app/github_client.py`                  | GitHub REST クライアント。`asyncio.gather` で並列取得                                            |
| `app/cache.py`                          | SQLite TTL キャッシュ。`json` シリアライズ、`expires_at` カラムで有効期限管理                    |
| `app/url_parser.py`                     | GitHub URL を `{type, owner, repo, number}` に分解                                               |
| `app/reviewer.py`                       | PR diff を Claude Haiku（失敗時 Ollama）へ送りコードレビューを返す                               |
| `app/config.py`                         | `dataclass Settings`。`GITHUB_TOKEN` / `GO_BACKEND_URL` / `CACHE_TTL_SECONDS` を環境変数から読む |
| `app/models.py`                         | Pydantic レスポンスモデル。Go 版との契約仕様                                                     |
| `backend-go/main.go`                    | Go エントリポイント。CORS ミドルウェア、chi ルーター、キャッシュ初期化                           |
| `backend-go/internal/handler/routes.go` | ルート登録。`fromCache[T]` ジェネリクスヘルパーで TTL キャッシュ透過アクセス                     |
| `backend-go/internal/github/client.go`  | Go 版 GitHub クライアント。`sync.WaitGroup` で並列取得                                           |
| `backend-go/internal/cache/`            | Go 版 SQLite TTL キャッシュ（`modernc.org/sqlite`、CGO 不要）                                    |

## リクエストフロー

### 1. 初期ロード

```
ブラウザ → GET /             → index.html を返す
ブラウザ → GET /api/config   → {go_backend_url: "https://..." | null}
```

`go_backend_url` が返ればヘッダのバックエンドトグルが表示される。

### 2. 通常分析（Analyze タブ）

```
ユーザー入力: https://github.com/torvalds/linux
ブラウザ → GET /api/analyze?url=... (X-GitHub-Token: xxx)
Python url_parser → {type:"repo", owner:"torvalds", repo:"linux"}
Python github_client.get_repo()
  ├── GET api.github.com/repos/torvalds/linux
  └── GET api.github.com/repos/torvalds/linux/languages  (並列)
SQLite cache ヒット → キャッシュから返す (TTL 300s)
           ミス → GitHub API 呼び出し → キャッシュ書き込み → レスポンス
```

### 3. ベンチマーク

```
ブラウザ → GET /api/benchmark?url=...  (常に Python へ)
Python:
  t0 = now()
  analyze(url)          ← 自分自身を計測
  python_ms = now() - t0

  if GO_BACKEND_URL:
    t1 = now()
    GET go_backend/api/analyze?url=...
    go_ms = now() - t1
    go_available = True
  else:
    go_ms = None
    go_available = False

レスポンス: {python_ms, go_ms, go_available, speedup}
```

`speedup` は `python_ms / go_ms`。Go が遅ければ 1 未満になる。

### 4. AI レビュー（PR のみ）

```
ブラウザ → GET /api/review?url=https://github.com/owner/repo/pull/N
Python → GitHub API で PR diff 取得
Python → Claude Haiku (ANTHROPIC_API_KEY) で diff レビュー
         失敗時 → Ollama (OLLAMA_URL) fallback
レスポンス: {review: "...", model_used: "claude-haiku" | "ollama"}
```

## データモデル（SQLite キャッシュ）

```sql
CREATE TABLE IF NOT EXISTS cache (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,    -- JSON シリアライズ済みレスポンス
    expires_at INTEGER NOT NULL  -- UNIX タイムスタンプ (秒)
);
```

Python 版・Go 版それぞれ独立したファイル（`cache.db` / `cache-go.db`）を持つ。
同一 URL への重複リクエストは TTL 内であれば GitHub API を呼ばない。

## 環境変数

| 変数                | 必須 | 説明                                                          |
| ------------------- | ---- | ------------------------------------------------------------- |
| `GITHUB_TOKEN`      | ○    | Fine-grained PAT (public repos read)                          |
| `GO_BACKEND_URL`    | —    | Go バックエンドの URL（Render fromService で自動注入）        |
| `CACHE_DB`          | —    | SQLite パス（デフォルト: `cache.db`）                         |
| `CACHE_TTL_SECONDS` | —    | キャッシュ有効期限秒数（デフォルト: 300）                     |
| `ANTHROPIC_API_KEY` | —    | AI レビュー用（省略時 Ollama fallback）                       |
| `OLLAMA_URL`        | —    | Ollama エンドポイント（デフォルト: `http://localhost:11434`） |
| `CORS_ORIGINS`      | —    | Go 版のみ。許可 Origin のカンマ区切り（`*` でワイルドカード） |

## デプロイ（Render Blueprint）

```
render.yaml
  github-engineer-dashboard-api  (Python)
    GO_BACKEND_URL  ← fromService: github-engineer-dashboard-go
  github-engineer-dashboard-go   (Go)
    CORS_ORIGINS    ← fromService: github-engineer-dashboard-api
```

両サービスがデプロイ完了後、Render が URL を相互注入する。
初回のみ Render Dashboard で `GITHUB_TOKEN` を両サービスに手動設定する。

## 認証フロー

```
X-GitHub-Token ヘッダ (ブラウザ送信)
    ↓ 存在すれば優先
GITHUB_TOKEN 環境変数 (サーバー側フォールバック)
```

トークン未設定・無効の場合は GitHub API が 401/403 を返し、Python がそのまま 401 を返す。
`/api/config` と `/healthz` のみ認証不要。

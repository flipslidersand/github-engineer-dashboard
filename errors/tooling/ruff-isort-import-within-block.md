# ruff / isort: 関数ブロック内 import の警告

## 症状

ruff の `E402` (モジュールレベル import が先頭に無い) または isort の `I001` が、
関数本体内に書かれた `import` 文に対してエラーを報告する。

```python
# NG: 関数内 import
def benchmark(...):
    import time
    import httpx as _httpx
    ...
```

```
E402 Module level import not at top of file
```

## 原因

PEP 8 および ruff のデフォルト設定は、`import` 文をモジュールの先頭に置くことを要求する。
関数スコープへの遅延 import は例外として認められるケースもあるが、
ruff はデフォルトで `E402` を関数内 import にも適用する。

## 解決策

```python
# OK: モジュールトップに移動
import time
import httpx

...

def benchmark(...):
    t0 = time.perf_counter()
    resp = httpx.get(...)
```

`# noqa: E402` を行末に付けて個別抑制することも可能だが、
モジュール先頭への移動が正しい対応。

## このリポジトリでの発生箇所

- `app/main.py` — `benchmark` ハンドラ内の `import time` / `import httpx as _httpx`
  - Issue: 関数内 import はモジュールレベルに移動すること
  - 参照: code-review findings #7 (efficiency angle)

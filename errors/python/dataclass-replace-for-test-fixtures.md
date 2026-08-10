---
title: "dataclass Settings のテストフィクスチャは dataclasses.replace() を使う"
tags: [python, dataclass, pytest, pydantic]
severity: low
date: "2026-08-09"
---

## 症状

`Settings` が Pydantic BaseModel ではなく `@dataclass` の場合、
テスト内で `.model_copy()` や `.model_dump()` を呼ぶと `AttributeError` になる。

```
AttributeError: 'Settings' object has no attribute 'model_copy'
```

## 原因

`app/config.py` の `Settings` は `@dataclass` で定義されている。
Pydantic v2 の `BaseModel` ではないため `.model_*` メソッドが存在しない。

## 解決策

```python
import dataclasses
base = _settings()
override = dataclasses.replace(base, go_backend_url="http://localhost:8080")
```

## 予防

`config.py` を開いて `class Settings` の継承元を確認する。
`dataclass` なら `dataclasses.replace()`、`BaseModel` なら `.model_copy(update={})` を使う。

# デモ GIF 録画手順

1. サービスが起動している状態で録画ツールを起動
   - macOS: [Gifox](https://gifox.app/) / [Kap](https://getkap.co/)
   - Linux: [Peek](https://github.com/phw/peek) / `ffmpeg` + `gifsicle`
   - Windows: [ScreenToGif](https://www.screentogif.com/)

2. 録画対象操作（推奨順）
   - **Analyze** タブ: `https://github.com/torvalds` を入力して Analyze
   - **Analyze** タブ: `https://github.com/torvalds/linux` を入力して Analyze
   - **Summary** タブ: 同じ URL で Summary
   - **Benchmark** タブ: URL を入力して Run → Python バーを確認
   - ヘッダの **Backend: Python | Go ⚡** トグルを切り替え（Go 接続済みの場合）

3. 録画ファイルを `docs/demo.gif` として保存

4. README.md の以下プレースホルダーを差し替え:
   ```
   ![demo](docs/demo.gif)
   ```

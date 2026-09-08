# KOKORIKO — 孤狐狸固

[English](README.md) · 日本語

『HUNTER×HUNTER』の軍儀を題材とした、非公式の対局・解析エンジン。商品版上級ルールをもとに、C++の探索とPythonの自己対局・評価モデル学習を実装しています。

## 起動

Linux、C++20対応コンパイラ、Ninja、[uv](https://docs.astral.sh/uv/)が必要です。

```bash
./scripts/bootstrap.sh
./scripts/kokoriko.sh
```

評価モデルは同梱しています。標準入力へ1行ずつJSONを送って操作します。

```json
{"cmd":"new"}
{"cmd":"legal"}
{"cmd":"search","ms":1000}
```

## 開発

ビルド・テスト・学習は [開発手順](docs/DEVELOPMENT.md)、CLIの操作は [入出力仕様](docs/PROTOCOL.md) を参照してください。

[ルール](RULES.md) · [比較対局](docs/ARENA.md) · [評価モデル](docs/MODELS.md) · [出典](docs/SOURCES.md)

## ライセンス

コード、ドキュメント、同梱モデルは [MIT License](LICENSE)。原作・公式商品の名称と権利は各権利者に帰属します。

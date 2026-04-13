# Kronos Trading Decision Engine

bitFlyer Lightning（Crypto CFD）上で動作する自動売買システム。
設計書: `C:\tool\claude\Kronos\kronos_v3.1_prompt_design.md`

## セッション開始時

`.claude/progress.md` を必ず読んでコンテキストを復元すること。

## 開発環境（2026-04-13 確認済み）

### ハードウェア
- GPU: RTX 4070 Ti SUPER（VRAM 16GB）— Kronos-large含め全モデル動作可
- NVIDIA Driver: 595.97 / 最大CUDA対応: 13.2

### Pythonランタイム
| 環境 | パス | バージョン | 用途 |
|------|------|-----------|------|
| conda base | `C:\Users\temun\miniconda3\python.exe` | 3.12.3 | デフォルトPython |
| Python 3.10 standalone | `C:\Users\temun\AppData\Local\Programs\Python\Python310\python.exe` | 3.10.11 | TensorRT専用（現状） |

**Kronos用conda環境: `kronos`（Python 3.10.20）** — 導入済み。

Pythonパス: `C:\Users\temun\miniconda3\envs\kronos\python.exe`

### 導入済みパッケージ（kronos env）
| パッケージ | バージョン |
|-----------|-----------|
| torch | 2.6.0+cu124（CUDA 12.4, RTX 4070 Ti SUPER 16GB 動作確認済み） |
| torchvision / torchaudio | 0.21.0+cu124 / 2.6.0+cu124 |
| transformers | 5.5.3 |
| accelerate | 1.13.0 |
| huggingface-hub | 1.10.1 |
| pybotters | 1.10.0 |
| anthropic | 0.94.0 |
| pydantic | 2.12.5 |
| numpy | 2.2.6 |
| pandas | 2.3.3 |
| scipy | 1.15.3 |
| einops | 0.8.1 |
| matplotlib | 3.10.8 |

### スクリプト実行方法
```bash
# conda activate が効かない場合は直接パス指定
C:/Users/temun/miniconda3/envs/kronos/python.exe src/xxx.py

# または conda run
conda run -n kronos python src/xxx.py
```

### Kronos モデルリポジトリ
- クローン先: `C:\tool\claude\Kronos\kronos_model\`
- sys.path に追加して `from model import Kronos, KronosTokenizer, KronosPredictor` で使用
- 動作確認済み: Kronos-small (24.7M params, ~70 it/s @ RTX 4070 Ti SUPER)
- HFキャッシュ: `C:\Users\temun\.cache\huggingface\hub\`
- 注意: Git Bash / Windows コンソールでは日本語表示が cp932 で化けるが動作は正常

### WSL2
未インストール。本番移行時に必要（`wsl --install` で導入）。

### 適用済みClaude Codeスキル（Kronos開発で使用）
- `feature-dev` — 機能実装の主ワークフロー
- `test-driven-development` — 金融ロジックのユニットテスト
- `systematic-debugging` — デバッグ手順
- `verification-before-completion` — 完了前チェック
- `insecure-defaults` / `sharp-edges` — セキュリティ確認（実装完了時）

## 設計原則

「計算はPython、判断はLLM」の完全分離（設計書 v3.1 継承）

## 技術スタック

- 予測モデル: Kronos-base（HuggingFace: `NeoQuasar/Kronos-base`）
- 取引判断LLM: claude-sonnet-4.6
- 取引所: bitFlyer Lightning Crypto CFD（`FX_BTC_JPY`）
- APIクライアント: pybotters
- 言語: Python 3.10+（PyTorch CUDA 12.x）
- 実行環境: Windows + WSL2（本番はWSL2推奨）

## 重要な設計書からの修正点

```python
MAX_LEVERAGE_ALLOWED = 2.0   # 金融庁規制（設計書の5.0から変更）
MAX_KELLY_FRACTION = 0.10    # v3.1.1暫定値（変更不要）
```

## ディレクトリ構成（予定）

```
Kronos/
├── CLAUDE.md
├── .claude/
│   └── progress.md          # セッション間進捗
├── src/
│   ├── kronos_preprocessor.py      # 設計書§2-1より移植
│   ├── kronos_output_validator.py  # 設計書§2-2より移植
│   ├── kronos_runner.py            # 設計書§2-3より移植・補完
│   ├── kronos_bridge.py            # Kronosブリッジアダプター（要実装）
│   ├── bitflyer_adapter.py         # bitFlyer APIアダプター（要実装）
│   ├── execution_manager.py        # 設計書§6より移植・補完
│   ├── realtime_monitor.py         # 設計書§7より移植・補完
│   └── data_pipeline.py            # OHLCVパイプライン（要実装）
├── prompts/
│   └── system_prompt_v3.1.txt      # 設計書§3より抽出（要作成）
├── tests/
│   └── test_preprocessor.py        # 設計書§4より移植
├── backtest/
│   └── run_backtest.py
└── requirements.txt
```

## Conventions（グローバル設定に追加）

- 金融ロジックの変更は必ずユニットテストで確認してから進める
- 注文執行に関わるコードは変更前に必ずユーザー確認を求める
- API秘密鍵・認証情報は `.env` に記載し、gitに追加しない

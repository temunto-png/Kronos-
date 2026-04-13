# Kronos Trading Decision Engine — セッション進捗

**最終更新:** 2026-04-13（STEP 3 完了）  
**ステータス:** STEP 1〜3 完了 → STEP 4（system_prompt_v3.1.txt 生成）待ち

---

## プロジェクト概要

bitFlyer Lightning（Crypto CFD）上で動作する自動売買システム。
設計書: `C:\tool\claude\Kronos\kronos_v3.1_prompt_design.md`

**設計原則:** 「計算はPython、判断はLLM」の完全分離

```
Kronosモデル（価格予測）
    ↓
kronos_preprocessor.py（Python前処理・全数値計算）
    ↓
Claude API（シグナル判断のみ）
    ↓
ExecutionManager（注文執行）
    ↓
RealtimeMonitor（独立常時監視）
```

---

## 確定事項

### 取引所
- **bitFlyer Lightning（Crypto CFD）**
  - product_code: `FX_BTC_JPY`（Lightning FX廃止後の継承）
  - ファンディングレート: 8時間ごと
  - レバレッジ上限: **2倍**（設計書の5倍から要修正）
  - API: REST + JSON-RPC 2.0 WebSocket
  - pybotters対応済み

### Kronosモデル
- リポジトリ: https://github.com/shiyu-coder/Kronos
- Hugging Face公開済み（`NeoQuasar/`org）
- **推奨モデル: Kronos-base**（102M params、VRAM ~0.8GB）
  - 開発・デバッグ段階: Kronos-small（起動速度優先）
  - バックテスト〜本番: Kronos-base

### ハードウェア
- GPU: RTX 4070 Ti SUPER（VRAM 16GB）→ Kronos-large含め全モデル動作可
- CPU: Ryzen 7 9800X3D
- RAM: 32GB
- OS: Windows（PowerShellベース）
- 本番稼働: WSL2移行を推奨

### 使用モデル
- 価格予測: Kronos-base
- 取引判断LLM: **claude-sonnet-4.6**（$3/$15 per MTok）
- 実装作業: Claude Code（Sonnet 4.6、現セッションと同モデル）

---

## 設計書から提供されているコード（実装済み）

| ファイル | 状態 | 備考 |
|---|---|---|
| `kronos_preprocessor.py` | ✅ 完全実装あり | 設計書 §2-1 |
| `kronos_output_validator.py` | ✅ 完全実装あり | 設計書 §2-2 |
| `kronos_runner.py` | ⚠️ 骨格のみ | 設計書 §2-3、取引所アダプター接続部が未実装 |
| `ExecutionManager` | ⚠️ 骨格のみ | 設計書 §6、bitFlyer向け実装が必要 |
| `RealtimeMonitor` | ⚠️ 骨格のみ | 設計書 §7、WebSocket実装が必要 |
| `system_prompt_v3.1.txt` | ⚠️ 内容は設計書§3にあり | ファイルとして切り出しが必要 |
| エッジケーステスト | ✅ pytest形式あり | 設計書 §4 |

---

## 未実装（要開発）

### 最優先（他が依存）
- [x] **Kronosブリッジアダプター** — `src/kronos_bridge.py` 実装済み

### 次フェーズ
- [ ] **bitFlyer APIアダプター**（pybotters使用推奨）
  - `user_data_stream()`: WebSocket User Data Stream
  - `market_order()`, `limit_order()`, `ioc_order()`
  - `get_account_snapshot()`, `cancel_all_open_orders()`

- [ ] **OHLCVデータパイプライン**
  - bitFlyer REST → pandas DataFrame（open/high/low/close/volume/amount）
  - `amount` = volume × price（bitFlyer独自計算が必要）
  - ファンディングレート履歴取得

- [ ] **`system_prompt_v3.1.txt`** 設計書§3から抜き出してファイル化

### インフラ
- [ ] **アラート通知**（`_send_alert()`実装）— FORCE_CLOSE失敗時の人間エスカレーション
- [ ] **状態永続化**（SQLiteなど）— session_state, position_state の再起動耐性
- [ ] **DriftMonitor** — 月次baseline更新ロジック（設計書 M7）

### キャリブレーション（バックテスト後）
- [ ] `WIN_RATE_LOGISTIC_A/B` の実データフィッティング
- [ ] バックテストフレームワーク（ルールベースフォールバック使用）

---

## 設計書からの重要な修正点

```python
# 国内規制対応（必須）
MAX_LEVERAGE_ALLOWED = 2.0   # 5.0 → 2.0（金融庁規制上限）

# Kelly入力の同一推定問題（暫定）
MAX_KELLY_FRACTION = 0.10    # 0.25 → 0.10（v3.1.1で引き下げ済み）

# VOLATILEレジーム追加（v3.1.1）
# SIGNAL_THRESHOLDS に "VOLATILE": 2.0 を追加済み
```

---

## 推奨着手順序

```
STEP 1 & 2: 環境構築 + Kronos-small 動作確認 ✅ 完了（2026-04-13）
  - conda env "kronos" (Python 3.10.20) 作成済み
  - PyTorch 2.6.0+cu124, transformers, anthropic, pybotters, einops 等 導入済み
  - CUDA動作確認済み（RTX 4070 Ti SUPER 16GB）
  - Kronos リポジトリ: C:\tool\claude\Kronos\kronos_model\ にクローン済み
  - Kronos-small ロード・推論テスト済み: 24.7M params, ~70 it/s（30ステップ）
  - テストスクリプト: tests/test_kronos_load.py

STEP 2: Kronosブリッジアダプター実装（最重要） ✅ 完了（2026-04-13）
  - src/kronos_bridge.py 実装済み
    - KronosBridge.forecast(): predict_batch(df_list=[df]*n_paths, sample_count=1) で確率的パスを並列生成
    - build_y_timestamp(): 予測タイムスタンプ生成ユーティリティ
  - tests/test_kronos_bridge.py: 18 Unit + 2 Integration = 20テスト全通過
    - 確率的パスの独立性（Integration）も確認済み

STEP 3: bitFlyer APIアダプター + データパイプライン実装 ✅ 完了（2026-04-13）
  - src/data_pipeline.py 実装済み
    - BitFlyerDataPipeline: get_ohlcv / get_funding_rate_history / start/stop
    - /v1/getexecutions ページング → pandas resample で OHLCV 集計
    - ファンディングレート: deque 蓄積 + 定期ポーリング（1時間ごと）
  - src/bitflyer_adapter.py 実装済み
    - BitFlyerAdapter: place_order(market/limit/ioc/stop_market) / cancel_order / cancel_all_orders
    - close_all_positions / close_position（スリッページチェック付き）
    - get_account_snapshot（daily_pnl_pct / drawdown_pct / HWM 管理）
    - user_data_stream（WebSocket + asyncio.Queue ブリッジ）
    - _StopWatcher: stop_market エミュレート（1秒 ticker ポーリング）
    - dry_run=True でモック動作
  - pytest-asyncio 1.3.0 追加、pytest.ini（asyncio_mode=auto）作成
  - tests/test_data_pipeline.py: 19テスト全通過
  - tests/test_bitflyer_adapter.py: 35テスト全通過
  - コードレビュー後の修正:
    - ws_connect を await 対応（WebSocketApp.__await__ 利用）
    - _StopWatcher._check_stops: ロック内で pop 実行（安全性向上）
    - MARKET 注文から time_in_force/minute_to_expire を除去
    - _fetch_executions: pybotters.Client(apis={}) に変更

STEP 4: system_prompt_v3.1.txt 生成
  - 設計書§3からファイル切り出し

STEP 5: 統合テスト
  - 設計書§4 エッジケーステスト実行
  - バックテスト（Kronos-base + ルールベースフォールバック）

STEP 6: WIN_RATE_LOGISTIC_A/B キャリブレーション
  - バックテスト結果からロジスティック回帰フィッティング
  - 本番移行条件: シャープレシオ>1.5 / 最大DD<15%

STEP 7: 本番稼働
  - WSL2環境構築
  - systemd/supervisordでデーモン化
```

---

## 参照リソース

| リソース | パス/URL |
|---|---|
| 設計書 | `C:\tool\claude\Kronos\kronos_v3.1_prompt_design.md` |
| Kronosリポジトリ | https://github.com/shiyu-coder/Kronos |
| Kronos論文 | https://arxiv.org/abs/2508.02739 |
| HuggingFace | `NeoQuasar/Kronos-base` |
| bitFlyer Lightning API | https://lightning.bitflyer.com/docs |
| pybotters docs | https://pybotters.readthedocs.io/ja/latest/ |

---

## 次セッションへの指示

1. このファイル（`C:\tool\claude\Kronos\.claude\progress.md`）を読んでコンテキストを復元する
2. 設計書 `C:\tool\claude\Kronos\kronos_v3.1_prompt_design.md` も参照
3. **STEP 4: `prompts/system_prompt_v3.1.txt` を設計書 §3 から抜き出して作成**
4. その後 STEP 5（統合テスト・バックテスト）へ進む

## 実装済みファイル一覧

| ファイル | 状態 | 概要 |
|---|---|---|
| `kronos_model/` | ✅ クローン済み | Kronosモデルリポジトリ（HFから自動DL） |
| `tests/test_kronos_load.py` | ✅ 通過 | Kronos-small ロード・推論スモークテスト |
| `src/kronos_bridge.py` | ✅ 実装済み | KronosBridge / build_y_timestamp |
| `tests/test_kronos_bridge.py` | ✅ 20/20通過 | Unit 18 + Integration 2 |
| `src/data_pipeline.py` | ✅ 実装済み | BitFlyerDataPipeline |
| `src/bitflyer_adapter.py` | ✅ 実装済み | BitFlyerAdapter + _StopWatcher |
| `tests/test_data_pipeline.py` | ✅ 19/19通過 | pytest-asyncio |
| `tests/test_bitflyer_adapter.py` | ✅ 35/35通過 | pytest-asyncio |
| `pytest.ini` | ✅ 作成済み | asyncio_mode=auto |

## 設計書から移植待ちのコード

| ファイル | 設計書 | 状態 |
|---|---|---|
| `src/kronos_preprocessor.py` | §2-1 | 未作成（コード完全記載済み → コピーするだけ） |
| `src/kronos_output_validator.py` | §2-2 | 未作成（同上） |
| `src/kronos_runner.py` | §2-3 | 未作成（骨格のみ、要補完） |
| `src/execution_manager.py` | §6 | 未作成（骨格のみ、要補完） |
| `src/realtime_monitor.py` | §7 | 未作成（骨格のみ、要補完） |
| `prompts/system_prompt_v3.1.txt` | §3 | 未作成（抜き出しのみ） |

## 要新規実装

| ファイル | 優先度 | 概要 |
|---|---|---|
| `src/bitflyer_adapter.py` | ✅完了 | pybotters使用、REST + WebSocket |
| `src/data_pipeline.py` | ✅完了 | OHLCV取得 + ファンディングレート |
| `src/kronos_bridge.py` | ✅完了 | predict_batch → kronos_forecast変換 |

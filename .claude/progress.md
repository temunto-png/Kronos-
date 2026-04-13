# Kronos Trading Decision Engine — セッション進捗

**最終更新:** 2026-04-13  
**ステータス:** STEP 1〜3 完了 → **次: STEP 4（system_prompt_v3.1.txt 生成）**

---

## 次セッションへの指示

1. このファイルを読んでコンテキストを復元
2. 設計書 `C:\tool\claude\Kronos\kronos_v3.1_prompt_design.md` 参照
3. **STEP 4: `prompts/system_prompt_v3.1.txt` を設計書 §3 から抜き出して作成**
4. その後 STEP 5（統合テスト・バックテスト）へ進む

---

## 実装状況

### 完了（STEP 1-3）
| ファイル | 概要 |
|---|---|
| `src/kronos_bridge.py` | KronosBridge / build_y_timestamp（テスト20/20） |
| `src/data_pipeline.py` | BitFlyerDataPipeline — OHLCV + ファンディングレート（テスト19/19） |
| `src/bitflyer_adapter.py` | BitFlyerAdapter + _StopWatcher（テスト35/35） |
| `pytest.ini` | asyncio_mode=auto |
| `kronos_model/` | クローン済み（Kronos-small 24.7M params, ~70 it/s 確認） |

環境: conda env `kronos` (Python 3.10.20), PyTorch 2.6.0+cu124, CUDA動作確認済み

### 未着手（設計書から移植）
| ファイル | 設計書 | 備考 |
|---|---|---|
| `prompts/system_prompt_v3.1.txt` | §3 | **STEP 4** — 次にやること |
| `src/kronos_preprocessor.py` | §2-1 | コード完全記載済み → コピーのみ |
| `src/kronos_output_validator.py` | §2-2 | 同上 |
| `src/kronos_runner.py` | §2-3 | 骨格あり、取引所接続部を補完 |
| `src/execution_manager.py` | §6 | 骨格あり、bitFlyer向け実装 |
| `src/realtime_monitor.py` | §7 | 骨格あり、WebSocket実装 |

### インフラ（後回し）
- `_send_alert()` — FORCE_CLOSE失敗時の人間エスカレーション
- 状態永続化（SQLite）— session_state, position_state
- DriftMonitor — 月次baseline更新（設計書 M7）

---

## 重要な設計修正点

```python
MAX_LEVERAGE_ALLOWED = 2.0   # 設計書の5.0 → 金融庁規制上限
MAX_KELLY_FRACTION = 0.10    # 設計書の0.25 → v3.1.1暫定値
# SIGNAL_THRESHOLDS に "VOLATILE": 2.0 追加済み（v3.1.1）
```

---

## ロードマップ

```
STEP 4: system_prompt_v3.1.txt（設計書§3から抜き出し）
STEP 5: 統合テスト（設計書§4エッジケース）+ バックテスト（Kronos-base）
STEP 6: WIN_RATE_LOGISTIC_A/B キャリブレーション（目標: シャープ>1.5 / DD<15%）
STEP 7: 本番稼働（WSL2 + systemd/supervisord）
```

---

## 参照リソース

| リソース | パス/URL |
|---|---|
| 設計書 | `C:\tool\claude\Kronos\kronos_v3.1_prompt_design.md` |
| Kronosリポジトリ | `C:\tool\claude\Kronos\kronos_model\` / https://github.com/shiyu-coder/Kronos |
| HuggingFace | `NeoQuasar/Kronos-base` |
| bitFlyer API | https://lightning.bitflyer.com/docs |

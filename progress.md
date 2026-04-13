# progress.md — STEP 3 実装ログ

---

## Session 1 (2026-04-13)

### 完了
- [x] 設計書 §6, §7 から exchange_client インターフェースを抽出
- [x] bitFlyer API エンドポイント・制約を調査（findings.md に記録）
- [x] ユーザーとスコープ・方針を確認（size_jpy統一 / stop_market emulation / 等）
- [x] task_plan.md, findings.md, progress.md 作成

### 未着手（次のアクション）
- [ ] P1: BitFlyerDataPipeline 実装（src/data_pipeline.py）
- [ ] P2: BitFlyerAdapter コア実装（src/bitflyer_adapter.py）
- [ ] P3: _StopWatcher 実装
- [ ] P4: user_data_stream() WebSocket実装
- [ ] P5: get_account_snapshot() + HWM管理
- [ ] P6: テスト作成・全通過確認
- [ ] P7: セキュリティチェック
- [ ] P8: progress.md 更新

### 判断・決定ログ
| 項目 | 決定 |
|---|---|
| OHLCV取得 | bitFlyer 公式 `/v1/getexecutions` 集計（外部依存なし） |
| ファンディング履歴 | 定期ポーリングで自前蓄積（bitFlyer に履歴APIなし） |
| stop_market | _StopWatcher で1秒ポーリングエミュレート（本番前にWS化推奨） |
| スコープ | bitflyer_adapter.py + data_pipeline.py 同時実装 |

---

## テスト結果ログ（実装後に記入）

| テストファイル | 結果 | 備考 |
|---|---|---|
| test_bitflyer_adapter.py | - | 未実施 |
| test_data_pipeline.py | - | 未実施 |

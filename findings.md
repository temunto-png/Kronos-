# findings.md — STEP 3 調査メモ

## 設計書インターフェース整理（2026-04-13）

### exchange_client が満たすべきメソッド

設計書 §6 ExecutionManager / §7 RealtimeMonitor が呼び出すメソッド:

```python
# 注文系
exchange.place_order(client_order_id, side, type, size_usd,
                     price=None, stop_price=None,
                     time_in_force=None, reduce_only=False)
  → {"order_id": str}

exchange.cancel_order(order_id)
exchange.cancel_all_orders()
exchange.close_all_positions(order_type, max_slippage_pct, reduce_only)
exchange.close_position(side, size_usd, reduce_only)
# ※ realtime_monitor.py では close_position(symbol, order_type, max_slippage_pct, reduce_only)
#    の形式も使用。side/size_jpy 形式に統一して対応。

# アカウント系
exchange.get_account_snapshot()
  → {
      "daily_pnl_pct": float,
      "drawdown_pct": float,
      "positions": [
        {"symbol": str, "unrealized_pnl_pct": float, ...}
      ]
    }

# WebSocket
exchange.user_data_stream()  # async context manager
  # async for event in ws:
  #   event["type"]: "ACCOUNT_UPDATE" | "ORDER_UPDATE"
  #   event["data"]: dict
```

### compute_session_state（§D-6）

```python
def compute_session_state(exchange_client) -> dict:
    account = exchange_client.get_account_snapshot()
    return {
        "daily_pnl_pct": _compute_daily_pnl(account),
        "current_drawdown_pct": _compute_drawdown(account),
        "consecutive_losses": _count_consecutive_losses(account),
    }
```
→ `get_account_snapshot()` が daily_pnl_pct / drawdown_pct を返せば OK。

---

## bitFlyer API 調査（2026-04-13）

### 注文タイプ（FX_BTC_JPY）
- `LIMIT` : 指値
- `MARKET` : 成行
- `STOP` : 逆指値（**Lightning FX では未対応**の可能性あり → エミュレート必要）
- `STOP_LIMIT` : 逆指値指値（同上）

→ **初期版では `STOP`/`STOP_LIMIT` はエミュレートで対応**

### 発注 API
```
POST /v1/me/sendchildorder
{
  "product_code": "FX_BTC_JPY",
  "child_order_type": "LIMIT" | "MARKET",
  "side": "BUY" | "SELL",
  "price": int,           // LIMIT のみ
  "size": float,          // BTC 建て
  "minute_to_expire": int, // GTC = 43200 (30日)
  "time_in_force": "GTC" | "IOC" | "FOK"
}
→ {"child_order_acceptance_id": "JRF..."}
```

注意:
- `size` は **BTC 建て** → JPY/BTC変換が必要
- `client_order_id` に相当: `child_order_acceptance_id` (取引所が払い出す)
- bitFlyer には `client_order_id` の受け取り機能なし → UUID管理はアダプター側

### キャンセル API
```
POST /v1/me/cancelchildorder
{"product_code": "...", "child_order_acceptance_id": "JRF..."}

POST /v1/me/cancelallchildorders
{"product_code": "FX_BTC_JPY"}
```

### ポジション取得
```
GET /v1/me/getpositions?product_code=FX_BTC_JPY
→ [
    {
      "product_code": "FX_BTC_JPY",
      "side": "BUY" | "SELL",
      "price": float,       // entry price
      "size": float,        // BTC
      "commission": float,
      "swap_point_accumulate": float,
      "require_collateral": float,
      "open_date": "...",
      "leverage": float,
      "pnl": float,
      "sfd": float
    }
  ]
```

### 証拠金残高
```
GET /v1/me/getcollateral
→ {
    "collateral": float,        // 証拠金元本
    "open_position_pnl": float, // 未実現損益
    "require_collateral": float,
    "keep_rate": float
  }
equity = collateral + open_position_pnl
```

### 約定履歴（市場全体）
```
GET /v1/getexecutions?product_code=FX_BTC_JPY&count=500&before=XXXX
→ [
    {"id": int, "side": "BUY"|"SELL", "price": float, "size": float,
     "exec_date": "2024-01-01T00:00:00.123", "buy_child_order_acceptance_id": "..."}
  ]
```
- 最大 500 件/リクエスト
- `before` でページング（id ベース）
- 時系列降順

### ファンディングレート
```
GET /v1/getfundingrate?product_code=FX_BTC_JPY
→ {
    "current_funding_rate": float,
    "next_funding_rate_settlement_date": "..."
  }
```
⚠ 履歴取得エンドポイントなし → bitFlyer のみでは過去データが取れない  
→ 対応策: `data_pipeline.py` で定期的にポーリングして自前で蓄積するか、  
         backtest ではファンディングコストを一定値（0.01%/8h）で近似する

### WebSocket (private)
```
endpoint: wss://ws.lightstream.bitflyer.com/json-rpc
認証: {"method": "auth", "params": {"api_key": "...", "timestamp": ..., "nonce": "...", "signature": "..."}}
購読: {"method": "subscribe", "params": {"channel": "child_order_events"}}

child_order_events イベント:
{
  "channel": "child_order_events",
  "message": {
    "product_code": "FX_BTC_JPY",
    "child_order_id": "JFX...",
    "child_order_acceptance_id": "JRF...",
    "event_date": "...",
    "event_type": "EXECUTION" | "ORDER_FAILED" | "CANCEL" | "EXPIRE",
    "size": float,           // EXECUTION時のみ: 約定サイズ
    "price": float,          // EXECUTION時のみ: 約定価格
    "outstanding_size": float, // 残量
    "commission": float,
    "sfd": float
  }
}
```

### pybotters での WebSocket 接続
```python
import pybotters
async with pybotters.Client(apis={"bitflyer": [api_key, api_secret]}) as client:
    ws = await client.ws_connect(
        "wss://ws.lightstream.bitflyer.com/json-rpc",
        send_json=[
            {"method": "subscribe", "params": {"channel": "child_order_events"}, "id": 1}
        ],
        hdlr_json=handler,
    )
```
pybotters は bitFlyer WebSocket の認証を自動処理する。

---

## OHLCVデータ方針（2026-04-13）

**採用: bitFlyer 公式 REST `/v1/getexecutions` から集計**

理由:
- 外部サービス依存なし（cryptowatch は有料プランが必要、Bybit ミラーは非公式）
- bitFlyer FX_BTC_JPY の公式データで最も正確
- 運用コスト: 0円

制限:
- 1回500件まで → 大量データはページング必要
- 1h OHLCV 512本 = 約20,000〜30,000 約定履歴（市場活況度による）
- レート制限: HTTP 200回/分（非認証）

`amount` フィールドの計算:
- bitFlyer executions には volume (BTC) あり、JPY amount は `price * size` で計算
- `amount = price * size` でOK

---

## dry_run モード

- `dry_run=True` にすると REST/WebSocket API 呼び出しをすべてスキップ
- 発注は成功したと仮定し、ランダムな order_id を返す
- デバッグ・バックテスト統合テスト用

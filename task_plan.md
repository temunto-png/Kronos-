# STEP 3: bitFlyer APIアダプター + データパイプライン 実装計画

**作成日:** 2026-04-13  
**更新日:** 2026-04-13（方針確定）  
**ステータス:** 計画確定・実装待ち  
**対象ファイル:** `src/bitflyer_adapter.py`, `src/data_pipeline.py`, `tests/test_bitflyer_adapter.py`, `tests/test_data_pipeline.py`

---

## 目的

ExecutionManager / RealtimeMonitor が依存する `exchange_client` インターフェースを
bitFlyer Lightning Crypto CFD (FX_BTC_JPY) + pybotters で実装する。

---

## スコープ確定（全項目確定 2026-04-13）

| 項目 | 決定内容 | 理由 |
|---|---|---|
| 単位系 | **JPY建て統一** (`size_jpy`) | bitFlyer は BTC/JPY 建て。USD換算は不要 |
| stop_market | **アダプター内でエミュレート** (`_StopWatcher`) | bitFlyer FX は LIMIT/MARKET のみ。今回スコープに含める |
| reduce_only | **アダプター内でエミュレート** | bitFlyer に未対応。ポジション取得→方向チェック |
| WebSocket | **pybotters child_order_events** | private チャンネルで約定/取消イベント取得 |
| account snapshot | **アダプター内で計算** | HWM (高値equity) を保持し drawdown_pct を導出 |
| OHLCV | **bitFlyer 公式 REST `/v1/getexecutions`** | 外部依存なし、追加コストなし |
| 今回のスコープ | **bitflyer_adapter.py + data_pipeline.py** | アダプターが mid_price 取得で pipeline に依存するため同時実装が効率的 |
| テスト | **pybotters をモック** | bitFlyer にサンドボックスなし |
| **async/sync** | **全部 async（案B）** | `user_data_stream()` が async 確定のため統一する |
| **ファンディングレート** | **インメモリ蓄積（案C）** | `/v1/getfundingrate` を定期ポーリングして `deque` に蓄積 |
| **WebSocket受け取り** | **asyncio.Queue ブリッジ** | `hdlr_json` コールバック → Queue → AsyncGenerator |

---

## アーキテクチャ概要

```
ExecutionManager
  └── BitFlyerAdapter.place_order(side, type, size_jpy, ...)
        ├── "market"      → sendchildorder(MARKET)
        ├── "limit"       → sendchildorder(LIMIT)
        ├── "ioc"         → sendchildorder(MARKET, time_in_force=IOC)
        └── "stop_market" → _StopWatcher に登録（バックグラウンドprice監視）

RealtimeMonitor
  └── BitFlyerAdapter.user_data_stream()
        └── pybotters ws_connect → child_order_events チャンネル
              → イベントを正規化して AsyncGenerator で yield

BitFlyerDataPipeline.get_ohlcv()
  └── /v1/getexecutions → ページング集計 → pandas OHLCV DataFrame
```

---

## ファイル設計（async 統一版）

### src/bitflyer_adapter.py

```python
# ===== カスタム例外 =====
class SlippageExceededError(Exception): ...
class InvalidStateTransitionError(Exception): ...

# ===== 内部データクラス =====
@dataclass
class _StopOrder:
    order_id: str                 # アダプター内UUID
    client_order_id: str
    side: str                     # "BUY" | "SELL"
    stop_price: float
    size_jpy: float
    reduce_only: bool
    triggered: bool = False

# ===== メインアダプター =====
class BitFlyerAdapter:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        product_code: str = "FX_BTC_JPY",
        dry_run: bool = False,
    ) -> None:
        # 内部状態
        self._equity_start_of_day: float | None  # UTC 00:00 時点equity (daily_pnl用)
        self._equity_start_date: date | None      # リセット日付
        self._hwm_equity: float | None            # High Water Mark (drawdown用)
        self._stop_watcher: _StopWatcher          # stop_market エミュレーター

    # ===== ExecutionManager 向け (全部 async) =====

    async def place_order(
        self,
        client_order_id: str,
        side: str,                    # "BUY" | "SELL"
        type: str,                    # "market" | "limit" | "ioc" | "stop_market"
        size_jpy: float,
        price: float | None = None,
        stop_price: float | None = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
    ) -> dict[str, str]:
        # returns {"order_id": str}
        # type="stop_market" → _StopWatcher に登録して即時リターン
        # reduce_only=True → _check_reduce_only() でポジション方向チェック

    async def cancel_order(self, order_id: str) -> None:
        # POST /v1/me/cancelchildorder

    async def cancel_all_orders(self) -> None:
        # POST /v1/me/cancelallchildorders

    async def close_all_positions(
        self,
        order_type: str = "ioc",
        max_slippage_pct: float = 2.0,
        reduce_only: bool = True,
    ) -> None:
        # ポジション取得 → IOC で close 試行
        # mid_price ± max_slippage_pct% を超えた場合 → SlippageExceededError

    async def close_position(
        self,
        side: str,
        size_jpy: float,
        reduce_only: bool = True,
    ) -> None:
        # 単一ポジション MARKET クローズ

    # ===== RealtimeMonitor 向け (全部 async) =====

    async def get_account_snapshot(self) -> dict:
        # GET /v1/me/getcollateral + /v1/me/getpositions
        # 戻り値:
        # {
        #   "daily_pnl_pct": float,   # UTC 00:00リセット
        #   "drawdown_pct": float,    # HWMからの下落率
        #   "positions": [
        #     {"symbol": str, "size": float, "side": str,
        #      "entry_price": float, "mark_price": float,
        #      "unrealized_pnl_pct": float}
        #   ]
        # }

    async def user_data_stream(self):
        # AsyncGenerator[dict, None]
        # async with pybotters.Client(...) as client:
        #     queue = asyncio.Queue()
        #     def hdlr(msg, ...): queue.put_nowait(_normalize_event(msg))
        #     await client.ws_connect(..., hdlr_json=hdlr)
        #     while True:
        #         yield await queue.get()
        # イベント形式: {"type": "ORDER_UPDATE"|"ACCOUNT_UPDATE", "data": dict}

    # ===== 内部ユーティリティ (全部 async) =====

    async def _get_mid_price(self) -> float:
        # GET /v1/ticker → (best_bid + best_ask) / 2

    async def _get_positions(self) -> list[dict]:
        # GET /v1/me/getpositions

    async def _check_reduce_only(self, side: str, size_jpy: float) -> None:
        # ポジション取得 → 反対方向のポジが存在するか確認
        # 存在しない場合 → InvalidStateTransitionError

    @staticmethod
    def _jpy_to_btc(size_jpy: float, price: float) -> float:
        # size_jpy / price（BTC建てに変換）

    @staticmethod
    def _normalize_order_event(msg: dict) -> dict | None:
        # child_order_events → {"type": "ORDER_UPDATE", "data": {...}} に正規化
        # EXECUTION / CANCEL / EXPIRE / ORDER_FAILED をマッピング

# ===== _StopWatcher (bitflyer_adapter.py 内) =====

class _StopWatcher:
    """stop_market 注文のエミュレーター（バックグラウンドタスク）"""

    def __init__(self, adapter: "BitFlyerAdapter") -> None:
        self._orders: dict[str, _StopOrder]   # order_id → _StopOrder
        self._adapter: "BitFlyerAdapter"

    def register(self, stop_order: _StopOrder) -> None:
        # pending 注文に追加

    async def run_forever(self) -> None:
        # /v1/ticker を 1秒ポーリング
        # BUY stop: current_price >= stop_price → place_order(type="market")
        # SELL stop: current_price <= stop_price → place_order(type="market")
        # トリガー後は orders から削除
```

---

### src/data_pipeline.py

```python
class BitFlyerDataPipeline:
    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        funding_rate_poll_interval: int = 3600,   # 秒。デフォルト1時間ごと
        funding_rate_history_len: int = 200,      # deque の最大長
    ) -> None:
        self._funding_history: deque[tuple[datetime, float]]  # (timestamp, rate)
        self._poll_task: asyncio.Task | None

    # ===== 公開 API (全部 async) =====

    async def start(self) -> None:
        # ファンディングレート定期ポーリングタスクを asyncio.create_task で起動

    async def stop(self) -> None:
        # ポーリングタスクをキャンセル

    async def get_ohlcv(
        self,
        product_code: str = "FX_BTC_JPY",
        candle_interval: str = "1h",
        n_candles: int = 512,
    ) -> pd.DataFrame:
        # columns: open, high, low, close, volume, amount
        # index: DatetimeIndex (UTC, tz-aware)
        # amount = price * size（JPY建て出来高）

    async def get_funding_rate_history(
        self,
        n_periods: int = 100,
    ) -> pd.Series:
        # self._funding_history deque から直近 n_periods 件を返す
        # index: DatetimeIndex (UTC), value: funding_rate (float)
        # deque が空の場合は1回即時ポーリングしてから返す

    async def get_current_funding_rate(self) -> float:
        # GET /v1/getfundingrate → current_funding_rate を返す
        # get_funding_rate_history() の補助。deque にも追記する

    # ===== 内部 =====

    async def _fetch_executions(
        self,
        product_code: str,
        count: int = 500,
        before: int | None = None,
    ) -> list[dict]:
        # GET /v1/getexecutions?product_code=...&count=500&before=XXX

    @staticmethod
    def _aggregate_ohlcv(
        executions: list[dict],
        candle_interval: str,
    ) -> pd.DataFrame:
        # exec_date でリサンプリング → OHLCV集計
        # amount = price * size

    async def _paginate_to_cover(
        self,
        product_code: str,
        candle_interval: str,
        n_candles: int,
    ) -> list[dict]:
        # 必要な本数をカバーするまで before ページング

    async def _poll_funding_rate_forever(self) -> None:
        # asyncio.sleep(funding_rate_poll_interval) ループ
        # _funding_history deque に (now_utc, rate) を追加
```

---

## 実装フェーズ（依存順）

```
P1 (data_pipeline)
  ↓
P2 (adapter core: place/cancel/close)
  ↓
P3 (_StopWatcher)
  ↓
P4 (user_data_stream WebSocket)
  ↓
P5 (get_account_snapshot + HWM)
  ↓
P6 (tests)
  ↓
P7 (security check)
  ↓
P8 (progress.md 更新)
```

| フェーズ | 内容 | 状態 | 依存 |
|---|---|---|---|
| P1 | `BitFlyerDataPipeline` 実装（get_ohlcv, ファンディングポーリング） | pending | なし |
| P2 | `BitFlyerAdapter` コアメソッド実装（place/cancel/close, _jpy_to_btc） | pending | P1（mid_price取得） |
| P3 | `_StopWatcher` (stop_market エミュレーション) 実装 | pending | P2 |
| P4 | `user_data_stream()` WebSocket + asyncio.Queue ブリッジ実装 | pending | P2 |
| P5 | `get_account_snapshot()` + daily_pnl / HWM / drawdown 管理実装 | pending | P2 |
| P6 | テスト（`test_data_pipeline.py`, `test_bitflyer_adapter.py`） | pending | P1〜P5 |
| P7 | セキュリティチェック（`insecure-defaults`, `sharp-edges`） | pending | P6 |
| P8 | `progress.md` 更新 | pending | P7 |

---

## 設計書からの修正・補足

### 設計書インターフェースとの差分

| 設計書 | 実装 | 理由 |
|---|---|---|
| `place_order(size_usd=...)` | `place_order(size_jpy=...)` | bitFlyer は JPY 建て |
| `close_position(symbol, ...)` | `close_position(side, size_jpy, ...)` | FX_BTC_JPY 単一ペア |
| `stop_market` ネイティブ | `_StopWatcher` で emulate | bitFlyer 非対応 |
| `reduce_only` パラメータ | ポジション取得→バリデーション | bitFlyer 非対応 |

### bitFlyer API 使用エンドポイント

| 用途 | エンドポイント | 認証 |
|---|---|---|
| ティッカー (mid_price) | `GET /v1/ticker` | 不要 |
| 発注 | `POST /v1/me/sendchildorder` | 必要 |
| キャンセル | `POST /v1/me/cancelchildorder` | 必要 |
| 全キャンセル | `POST /v1/me/cancelallchildorders` | 必要 |
| ポジション取得 | `GET /v1/me/getpositions` | 必要 |
| 証拠金残高 | `GET /v1/me/getcollateral` | 必要 |
| 約定履歴(自分) | `GET /v1/me/getexecutions` | 必要 |
| 約定履歴(市場) | `GET /v1/getexecutions` | 不要 |
| ファンディングレート | `GET /v1/getfundingrate` | 不要 |
| WebSocket (private) | `wss://ws.lightstream.bitflyer.com/json-rpc` | 要 JSON-RPC 2.0 認証 |
| WS チャンネル | `child_order_events` | 要チャンネル認証 |

### _StopWatcher の注意事項

- 初期版: `/v1/ticker` を 1 秒ポーリング（シンプルで確実）
- 本番前改善: WebSocket 板情報 (`lightning_board_snapshot`) で低レイテンシ化
- スリッページ: 条件達成後も MARKET 注文のため、実際のトリガー価格と乖離が発生しうる
- 未実行リスク: adapter 再起動時に stop 注文情報は消失する（本番前に永続化が必要）

### get_account_snapshot() の計算ロジック

```
daily_pnl_pct:
  - UTC 00:00 時点の equity をスナップショット（初回呼び出し時に記録）
  - equity = collateral + unrealized_pnl
  - daily_pnl_pct = (equity_now - equity_start_of_day) / equity_start_of_day * 100

drawdown_pct:
  - インスタンス生成時から equity の HWM (High Water Mark) を追跡
  - drawdown_pct = (hwm - equity_now) / hwm * 100
```

---

## テスト方針（pytest-asyncio 使用）

```
tests/test_data_pipeline.py
  - @pytest.mark.asyncio で全テストを非同期実行
  - mock: aiohttp.ClientSession または pybotters.Client をパッチ
  - test: get_ohlcv (1h/4h/1d, 各足で正しいOHLCV集計)
  - test: ページング（n_candles > 500 でページング発生）
  - test: amount = price * size 計算
  - test: get_funding_rate_history（deque から返却、空deque時は即時fetch）
  - test: start()/stop() でポーリングタスクの起動・停止

tests/test_bitflyer_adapter.py
  - @pytest.mark.asyncio で全テストを非同期実行
  - mock: pybotters.Client.request() / ws_connect() をパッチ
  - test: place_order(market/limit/ioc) → sendchildorder 呼び出し確認
  - test: place_order(stop_market) → _StopWatcher.register() 呼び出し確認
  - test: cancel_order, cancel_all_orders
  - test: close_all_positions（スリッページ上限チェック: 超過でSlippageExceededError）
  - test: reduce_only バリデーション（反対ポジなし → InvalidStateTransitionError）
  - test: get_account_snapshot (daily_pnl 計算, HWM更新, drawdown計算)
  - test: user_data_stream → EXECUTION/CANCEL/EXPIRE/ORDER_FAILED イベント正規化
  - test: dry_run モード（API呼び出しなし、ランダムorder_id返却）
  - test: _StopWatcher.run_forever() → 条件達成でplace_order呼び出し

マーカー:
  - @pytest.mark.unit      : pybottersモック使用（通常実行）
  - @pytest.mark.integration: 実API呼び出し（明示的に除外して実行）
```

---

## 未解決事項（実装中に確認）

1. **pybotters WebSocket 認証方式**  
   → `pybotters.Client(apis={"bitflyer": [api_key, api_secret]})` の形式で自動処理。
   → `ws_connect` 呼び出し時に JSON-RPC `auth` メソッドを自動送信するか実装時に確認。

2. **`child_order_events` の event_type マッピング**  
   → findings.md に記載済み: `"EXECUTION" | "ORDER_FAILED" | "CANCEL" | "EXPIRE"`
   → ORDER_UPDATE の `status` フィールドへの正規化ルール:
   ```
   EXECUTION + outstanding_size==0 → "FILLED"
   EXECUTION + outstanding_size>0  → "PARTIALLY_FILLED"
   CANCEL / EXPIRE                 → "CANCELLED"
   ORDER_FAILED                    → "EXPIRED"（失敗扱い）
   ```

3. **pybotters のレスポンス取得方法（aiohttp ベース）**  
   → `client.get(url)` / `client.post(url, json=body)` でレスポンス取得
   → `await resp.json()` で dict 取得。ステータスコード確認が必要。

4. **getexecutions ページング上限**  
   → 500件/req。1h足 512本には約5,000〜30,000件必要 → 10〜60 リクエスト。
   → レート制限: HTTP 200回/分（非認証）→ 0.3秒 sleep を挟む。

---

## Errors Encountered

| Error | Attempt | Resolution |
|---|---|---|
| (未着手) | - | - |

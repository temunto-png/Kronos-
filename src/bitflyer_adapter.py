"""
bitflyer_adapter.py
bitFlyer Lightning Crypto CFD (FX_BTC_JPY) 向け取引所アダプター。

設計:
  - ExecutionManager / RealtimeMonitor が依存する exchange_client インターフェースを実装
  - 全メソッドが async
  - stop_market は _StopWatcher でエミュレート（bitFlyer 非対応）
  - reduce_only はポジション取得→方向チェックでエミュレート（bitFlyer 非対応）
  - dry_run=True でAPI呼び出しなしのモック動作
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import AsyncGenerator, Optional

import pybotters

logger = logging.getLogger("kronos.bitflyer_adapter")

_BASE_URL = "https://api.bitflyer.com"
_WS_URL = "wss://ws.lightstream.bitflyer.com/json-rpc"

# GTC 有効期限: 30 日（bitFlyer は分単位）
_GTC_MINUTE_TO_EXPIRE = 43200


# --------------------------------------------------------------------------
# カスタム例外
# --------------------------------------------------------------------------

class SlippageExceededError(Exception):
    """成行クローズ時のスリッページが上限を超過した。"""


class InvalidStateTransitionError(Exception):
    """reduce_only バリデーション失敗（クローズすべき反対方向ポジションが存在しない）。"""


# --------------------------------------------------------------------------
# 内部データクラス
# --------------------------------------------------------------------------

@dataclass
class _StopOrder:
    order_id: str
    client_order_id: str
    side: str           # "BUY" | "SELL"
    stop_price: float
    size_jpy: float
    reduce_only: bool
    triggered: bool = False


# --------------------------------------------------------------------------
# _StopWatcher
# --------------------------------------------------------------------------

class _StopWatcher:
    """
    stop_market 注文のエミュレーター。
    1 秒ごとに /v1/ticker をポーリングし、条件達成時に MARKET 注文を発行する。

    注意:
    - アダプター再起動時に stop 注文情報は消失する（本番前に永続化が必要）
    - 条件達成後も MARKET 注文のためスリッページが発生しうる
    """

    def __init__(self, adapter: "BitFlyerAdapter") -> None:
        self._adapter = adapter
        self._orders: dict[str, _StopOrder] = {}
        self._lock = asyncio.Lock()

    def register(self, stop_order: _StopOrder) -> None:
        """stop_market 注文を登録する。"""
        self._orders[stop_order.order_id] = stop_order
        logger.info(
            "StopWatcher: 登録 order_id=%s side=%s stop_price=%.0f size_jpy=%.0f",
            stop_order.order_id, stop_order.side,
            stop_order.stop_price, stop_order.size_jpy,
        )

    async def cancel(self, order_id: str) -> None:
        """stop_market 注文をキャンセルする。"""
        async with self._lock:
            self._orders.pop(order_id, None)

    async def run_forever(self) -> None:
        """バックグラウンドで stop 条件を監視し続ける。"""
        logger.info("StopWatcher: 起動")
        while True:
            try:
                await self._check_stops()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("StopWatcher: ポーリングエラー %s", exc)
            await asyncio.sleep(1.0)

    async def _check_stops(self) -> None:
        if not self._orders:
            return

        current_price = await self._adapter._get_mid_price()
        triggered_orders: list[_StopOrder] = []

        async with self._lock:
            for order_id, order in list(self._orders.items()):
                if order.triggered:
                    continue
                if order.side == "BUY" and current_price >= order.stop_price:
                    order.triggered = True
                    triggered_orders.append(order)
                    self._orders.pop(order_id, None)
                elif order.side == "SELL" and current_price <= order.stop_price:
                    order.triggered = True
                    triggered_orders.append(order)
                    self._orders.pop(order_id, None)

        for order in triggered_orders:
            logger.info(
                "StopWatcher: トリガー order_id=%s side=%s price=%.0f",
                order.order_id, order.side, current_price,
            )
            try:
                await self._adapter.place_order(
                    client_order_id=f"{order.client_order_id}_triggered",
                    side=order.side,
                    type="market",
                    size_jpy=order.size_jpy,
                    reduce_only=order.reduce_only,
                )
            except Exception as exc:
                logger.error(
                    "StopWatcher: MARKET 発注失敗 order_id=%s: %s", order_id, exc
                )


# --------------------------------------------------------------------------
# BitFlyerAdapter
# --------------------------------------------------------------------------

class BitFlyerAdapter:
    """
    bitFlyer Lightning Crypto CFD (FX_BTC_JPY) 向け取引所アダプター。

    ExecutionManager / RealtimeMonitor が依存する exchange_client インターフェースを実装する。
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        product_code: str = "FX_BTC_JPY",
        dry_run: bool = False,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._product_code = product_code
        self._dry_run = dry_run

        # daily_pnl 管理（UTC 00:00 リセット）
        self._hwm_equity: Optional[float] = None
        self._equity_start_of_day: Optional[float] = None
        self._equity_start_date: Optional[date] = None

        # stop_market エミュレーター
        self._stop_watcher = _StopWatcher(self)
        self._stop_watcher_task: Optional[asyncio.Task] = None

    def _make_client(self) -> pybotters.Client:
        """認証付き pybotters.Client を生成する。"""
        return pybotters.Client(apis={"bitflyer": [self._api_key, self._api_secret]})

    async def _ensure_stop_watcher(self) -> None:
        """_StopWatcher バックグラウンドタスクが起動していなければ起動する。"""
        if self._stop_watcher_task is None or self._stop_watcher_task.done():
            self._stop_watcher_task = asyncio.create_task(
                self._stop_watcher.run_forever()
            )

    # ------------------------------------------------------------------
    # ExecutionManager 向けメソッド
    # ------------------------------------------------------------------

    async def place_order(
        self,
        client_order_id: str,
        side: str,
        type: str,
        size_jpy: float,
        price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: str = "GTC",
        reduce_only: bool = False,
    ) -> dict[str, str]:
        """
        発注する。

        Args:
            client_order_id: アダプター内の注文識別子（bitFlyer には送信しない）
            side: "BUY" | "SELL"
            type: "market" | "limit" | "ioc" | "stop_market"
            size_jpy: 発注サイズ（JPY建て）
            price: 指値価格（limit のみ必須）
            stop_price: ストップ価格（stop_market のみ必須）
            time_in_force: "GTC" | "IOC" | "FOK"（market/ioc は自動設定）
            reduce_only: True のとき反対方向ポジション存在チェックを行う

        Returns:
            {"order_id": str}
        """
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise ValueError(f"side は 'BUY' または 'SELL': {side!r}")

        if reduce_only:
            await self._check_reduce_only(side, size_jpy)

        if type == "stop_market":
            if stop_price is None:
                raise ValueError("stop_market 注文には stop_price が必要")
            order_id = str(uuid.uuid4())
            stop_order = _StopOrder(
                order_id=order_id,
                client_order_id=client_order_id,
                side=side,
                stop_price=stop_price,
                size_jpy=size_jpy,
                reduce_only=reduce_only,
            )
            self._stop_watcher.register(stop_order)
            await self._ensure_stop_watcher()
            return {"order_id": order_id}

        if self._dry_run:
            order_id = f"DRY-{uuid.uuid4().hex[:8]}"
            logger.info("dry_run: place_order client_order_id=%s → %s", client_order_id, order_id)
            return {"order_id": order_id}

        mid_price = await self._get_mid_price()
        size_btc = self._jpy_to_btc(size_jpy, price if price is not None else mid_price)

        body: dict = {
            "product_code": self._product_code,
            "side": side,
            "size": size_btc,
        }

        if type == "market":
            body["child_order_type"] = "MARKET"
        elif type == "ioc":
            body["child_order_type"] = "MARKET"
            body["time_in_force"] = "IOC"
        elif type == "limit":
            if price is None:
                raise ValueError("limit 注文には price が必要")
            body["child_order_type"] = "LIMIT"
            body["price"] = int(price)
            body["time_in_force"] = time_in_force
            body["minute_to_expire"] = _GTC_MINUTE_TO_EXPIRE
        else:
            raise ValueError(f"未対応の order type: {type!r}")

        async with self._make_client() as client:
            async with client.post(
                f"{_BASE_URL}/v1/me/sendchildorder",
                data=body,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        order_id = data.get("child_order_acceptance_id", "")
        logger.info(
            "place_order: %s %s size_jpy=%.0f → order_id=%s",
            side, type, size_jpy, order_id,
        )
        return {"order_id": order_id}

    async def cancel_order(self, order_id: str) -> None:
        """注文をキャンセルする。stop_market エミュレート注文にも対応。"""
        # stop_market の場合は _StopWatcher から削除
        await self._stop_watcher.cancel(order_id)

        if self._dry_run:
            logger.info("dry_run: cancel_order order_id=%s", order_id)
            return

        body = {
            "product_code": self._product_code,
            "child_order_acceptance_id": order_id,
        }
        async with self._make_client() as client:
            async with client.post(
                f"{_BASE_URL}/v1/me/cancelchildorder",
                data=body,
            ) as resp:
                resp.raise_for_status()

        logger.info("cancel_order: order_id=%s", order_id)

    async def cancel_all_orders(self) -> None:
        """全注文をキャンセルする。"""
        if self._dry_run:
            logger.info("dry_run: cancel_all_orders")
            return

        body = {"product_code": self._product_code}
        async with self._make_client() as client:
            async with client.post(
                f"{_BASE_URL}/v1/me/cancelallchildorders",
                data=body,
            ) as resp:
                resp.raise_for_status()

        logger.info("cancel_all_orders")

    async def close_all_positions(
        self,
        order_type: str = "ioc",
        max_slippage_pct: float = 2.0,
        reduce_only: bool = True,
    ) -> None:
        """
        全ポジションをクローズする。

        mid_price と entry_price の乖離が max_slippage_pct% を超える場合は
        SlippageExceededError を送出する（人間エスカレーション用）。
        """
        positions = await self._get_positions()
        if not positions:
            logger.info("close_all_positions: ポジションなし")
            return

        mid_price = await self._get_mid_price()

        for pos in positions:
            pos_side = pos["side"]  # "BUY" | "SELL"
            pos_size_btc = float(pos["size"])
            entry_price = float(pos["price"])

            if entry_price > 0:
                # entry と mid の乖離が大きい場合は人間にエスカレーション
                price_deviation_pct = abs(mid_price - entry_price) / entry_price * 100
                if price_deviation_pct > max_slippage_pct:
                    raise SlippageExceededError(
                        f"価格乖離 {price_deviation_pct:.2f}% が上限 {max_slippage_pct:.2f}% を超過 "
                        f"(entry={entry_price:.0f}, mid={mid_price:.0f})"
                    )

            close_side = "SELL" if pos_side == "BUY" else "BUY"
            size_jpy = pos_size_btc * mid_price

            await self.close_position(
                side=close_side,
                size_jpy=size_jpy,
                reduce_only=reduce_only,
            )

    async def close_position(
        self,
        side: str,
        size_jpy: float,
        reduce_only: bool = True,
    ) -> None:
        """単一ポジションを MARKET でクローズする。"""
        await self.place_order(
            client_order_id=f"close-{uuid.uuid4().hex[:8]}",
            side=side,
            type="market",
            size_jpy=size_jpy,
            reduce_only=reduce_only,
        )

    # ------------------------------------------------------------------
    # RealtimeMonitor 向けメソッド
    # ------------------------------------------------------------------

    async def get_account_snapshot(self) -> dict:
        """
        アカウントスナップショットを返す。

        Returns:
            {
                "daily_pnl_pct": float,   # UTC 00:00 リセット
                "drawdown_pct": float,    # HWM からの下落率
                "positions": [
                    {
                        "symbol": str,
                        "size": float,
                        "side": str,
                        "entry_price": float,
                        "mark_price": float,
                        "unrealized_pnl_pct": float,
                    }
                ]
            }
        """
        if self._dry_run:
            return {"daily_pnl_pct": 0.0, "drawdown_pct": 0.0, "positions": []}

        async with self._make_client() as client:
            async with client.get(f"{_BASE_URL}/v1/me/getcollateral") as resp:
                resp.raise_for_status()
                collateral_data = await resp.json()

            async with client.get(
                f"{_BASE_URL}/v1/me/getpositions",
                params={"product_code": self._product_code},
            ) as resp:
                resp.raise_for_status()
                positions_data = await resp.json()

        collateral = float(collateral_data["collateral"])
        open_pnl = float(collateral_data["open_position_pnl"])
        equity = collateral + open_pnl

        # daily_pnl_pct: UTC 00:00 時点の equity からの変化率
        today_utc = datetime.now(timezone.utc).date()
        if self._equity_start_date != today_utc or self._equity_start_of_day is None:
            self._equity_start_of_day = equity
            self._equity_start_date = today_utc

        daily_pnl_pct = (
            (equity - self._equity_start_of_day) / self._equity_start_of_day * 100
            if self._equity_start_of_day > 0
            else 0.0
        )

        # drawdown_pct: HWM からの下落率
        if self._hwm_equity is None or equity > self._hwm_equity:
            self._hwm_equity = equity

        drawdown_pct = (
            (self._hwm_equity - equity) / self._hwm_equity * 100
            if self._hwm_equity > 0
            else 0.0
        )

        # ポジション正規化
        mid_price = await self._get_mid_price()
        positions = []
        for pos in positions_data:
            entry_price = float(pos["price"])
            pos_size = float(pos["size"])
            pos_side = pos["side"]

            if entry_price > 0:
                if pos_side == "BUY":
                    unrealized_pnl_pct = (mid_price - entry_price) / entry_price * 100
                else:
                    unrealized_pnl_pct = (entry_price - mid_price) / entry_price * 100
            else:
                unrealized_pnl_pct = 0.0

            positions.append({
                "symbol": self._product_code,
                "size": pos_size,
                "side": pos_side,
                "entry_price": entry_price,
                "mark_price": mid_price,
                "unrealized_pnl_pct": unrealized_pnl_pct,
            })

        return {
            "daily_pnl_pct": daily_pnl_pct,
            "drawdown_pct": drawdown_pct,
            "positions": positions,
        }

    async def user_data_stream(self) -> AsyncGenerator[dict, None]:
        """
        WebSocket で child_order_events を受信し、正規化イベントを yield する。

        pybotters が bitFlyer WebSocket の認証を自動処理する。

        Yields:
            {"type": "ORDER_UPDATE", "data": {...}}
        """
        queue: asyncio.Queue[dict] = asyncio.Queue()

        def hdlr_json(msg: dict, *args, **kwargs) -> None:
            event = self._normalize_order_event(msg)
            if event is not None:
                queue.put_nowait(event)

        async with pybotters.Client(
            apis={"bitflyer": [self._api_key, self._api_secret]}
        ) as client:
            await client.ws_connect(
                _WS_URL,
                send_json=[
                    {
                        "method": "subscribe",
                        "params": {"channel": "child_order_events"},
                        "id": 1,
                    }
                ],
                hdlr_json=hdlr_json,
            )
            logger.info("user_data_stream: WebSocket 接続開始")
            while True:
                event = await queue.get()
                yield event

    # ------------------------------------------------------------------
    # 内部ユーティリティ
    # ------------------------------------------------------------------

    async def _get_mid_price(self) -> float:
        """GET /v1/ticker → (best_bid + best_ask) / 2"""
        async with pybotters.Client() as client:
            async with client.get(
                f"{_BASE_URL}/v1/ticker",
                params={"product_code": self._product_code},
                auth=None,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        return (float(data["best_bid"]) + float(data["best_ask"])) / 2

    async def _get_positions(self) -> list[dict]:
        """GET /v1/me/getpositions"""
        if self._dry_run:
            return []

        async with self._make_client() as client:
            async with client.get(
                f"{_BASE_URL}/v1/me/getpositions",
                params={"product_code": self._product_code},
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def _check_reduce_only(self, side: str, size_jpy: float) -> None:
        """
        reduce_only バリデーション。
        クローズすべき反対方向ポジションが存在しない場合 InvalidStateTransitionError を送出する。
        """
        positions = await self._get_positions()
        opposite_side = "SELL" if side == "BUY" else "BUY"
        has_opposite = any(p["side"] == opposite_side for p in positions)
        if not has_opposite:
            raise InvalidStateTransitionError(
                f"reduce_only=True だが {opposite_side} ポジションが存在しない"
            )

    @staticmethod
    def _jpy_to_btc(size_jpy: float, price: float) -> float:
        """JPY 建てサイズを BTC 建てに変換する。"""
        if price <= 0:
            raise ValueError(f"price は正の値が必要: {price}")
        return size_jpy / price

    @staticmethod
    def _normalize_order_event(msg: dict) -> Optional[dict]:
        """
        child_order_events WebSocket メッセージ（JSON-RPC 2.0）を正規化する。

        event_type → status マッピング:
            EXECUTION + outstanding_size == 0 → "FILLED"
            EXECUTION + outstanding_size > 0  → "PARTIALLY_FILLED"
            CANCEL | EXPIRE                   → "CANCELLED"
            ORDER_FAILED                      → "EXPIRED"

        Returns:
            {"type": "ORDER_UPDATE", "data": {...}} または None（無関係メッセージ）
        """
        if msg.get("method") != "channelMessage":
            return None

        params = msg.get("params", {})
        if params.get("channel") != "child_order_events":
            return None

        message = params.get("message", {})
        event_type = message.get("event_type")
        outstanding_size = float(message.get("outstanding_size", 0))

        if event_type == "EXECUTION":
            status = "FILLED" if outstanding_size == 0 else "PARTIALLY_FILLED"
        elif event_type in ("CANCEL", "EXPIRE"):
            status = "CANCELLED"
        elif event_type == "ORDER_FAILED":
            status = "EXPIRED"
        else:
            return None

        return {
            "type": "ORDER_UPDATE",
            "data": {
                "order_id": message.get("child_order_acceptance_id", ""),
                "status": status,
                "side": message.get("side", ""),
                "size": float(message.get("size", 0)),
                "price": float(message.get("price", 0)),
                "outstanding_size": outstanding_size,
                "event_type": event_type,
                "event_date": message.get("event_date", ""),
            },
        }

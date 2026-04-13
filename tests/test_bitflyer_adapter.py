"""
test_bitflyer_adapter.py
BitFlyerAdapter のユニットテスト

実行:
    conda run -n kronos python -m pytest tests/test_bitflyer_adapter.py -v
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.bitflyer_adapter import (
    BitFlyerAdapter,
    SlippageExceededError,
    InvalidStateTransitionError,
    _StopWatcher,
    _StopOrder,
)


# ------------------------------------------------------------------
# ヘルパー
# ------------------------------------------------------------------

def _adapter(dry_run: bool = False) -> BitFlyerAdapter:
    return BitFlyerAdapter(
        api_key="test_key",
        api_secret="test_secret",
        product_code="FX_BTC_JPY",
        dry_run=dry_run,
    )


def _make_resp_mock(json_data, status: int = 200):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(return_value=json_data)
    resp.status = status
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_client_mock(get_resp=None, post_resp=None):
    """pybotters.Client のモックを生成する。"""
    client = MagicMock()
    if get_resp is not None:
        client.get.return_value = get_resp
    if post_resp is not None:
        client.post.return_value = post_resp
    client.ws_connect = MagicMock()

    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)
    return client_ctx, client


TICKER_RESP = {"best_bid": 9_980_000.0, "best_ask": 10_020_000.0}  # mid = 10_000_000


# ------------------------------------------------------------------
# テスト: _jpy_to_btc (純粋関数)
# ------------------------------------------------------------------

@pytest.mark.unit
def test_jpy_to_btc_basic():
    assert BitFlyerAdapter._jpy_to_btc(10_000_000, 10_000_000) == pytest.approx(1.0)


@pytest.mark.unit
def test_jpy_to_btc_fraction():
    assert BitFlyerAdapter._jpy_to_btc(5_000_000, 10_000_000) == pytest.approx(0.5)


@pytest.mark.unit
def test_jpy_to_btc_zero_price_raises():
    with pytest.raises(ValueError):
        BitFlyerAdapter._jpy_to_btc(1_000_000, 0)


# ------------------------------------------------------------------
# テスト: _normalize_order_event (純粋関数)
# ------------------------------------------------------------------

@pytest.mark.unit
def test_normalize_execution_filled():
    """EXECUTION + outstanding_size==0 → FILLED"""
    msg = {
        "method": "channelMessage",
        "params": {
            "channel": "child_order_events",
            "message": {
                "event_type": "EXECUTION",
                "outstanding_size": 0,
                "child_order_acceptance_id": "JRF001",
                "side": "BUY",
                "size": 0.01,
                "price": 10_000_000.0,
                "event_date": "2024-01-01T00:00:00",
            },
        },
    }
    event = BitFlyerAdapter._normalize_order_event(msg)
    assert event is not None
    assert event["type"] == "ORDER_UPDATE"
    assert event["data"]["status"] == "FILLED"
    assert event["data"]["order_id"] == "JRF001"


@pytest.mark.unit
def test_normalize_execution_partially_filled():
    """EXECUTION + outstanding_size>0 → PARTIALLY_FILLED"""
    msg = {
        "method": "channelMessage",
        "params": {
            "channel": "child_order_events",
            "message": {
                "event_type": "EXECUTION",
                "outstanding_size": 0.005,
                "child_order_acceptance_id": "JRF002",
                "side": "SELL",
                "size": 0.005,
                "price": 10_000_000.0,
                "event_date": "2024-01-01T00:00:00",
            },
        },
    }
    event = BitFlyerAdapter._normalize_order_event(msg)
    assert event["data"]["status"] == "PARTIALLY_FILLED"


@pytest.mark.unit
@pytest.mark.parametrize("event_type", ["CANCEL", "EXPIRE"])
def test_normalize_cancel_expire(event_type):
    """CANCEL / EXPIRE → CANCELLED"""
    msg = {
        "method": "channelMessage",
        "params": {
            "channel": "child_order_events",
            "message": {
                "event_type": event_type,
                "outstanding_size": 0.01,
                "child_order_acceptance_id": "JRF003",
                "side": "BUY",
                "size": 0,
                "price": 0,
                "event_date": "2024-01-01T00:00:00",
            },
        },
    }
    event = BitFlyerAdapter._normalize_order_event(msg)
    assert event["data"]["status"] == "CANCELLED"


@pytest.mark.unit
def test_normalize_order_failed():
    """ORDER_FAILED → EXPIRED"""
    msg = {
        "method": "channelMessage",
        "params": {
            "channel": "child_order_events",
            "message": {
                "event_type": "ORDER_FAILED",
                "outstanding_size": 0.01,
                "child_order_acceptance_id": "JRF004",
                "side": "BUY",
                "size": 0,
                "price": 0,
                "event_date": "2024-01-01T00:00:00",
            },
        },
    }
    event = BitFlyerAdapter._normalize_order_event(msg)
    assert event["data"]["status"] == "EXPIRED"


@pytest.mark.unit
def test_normalize_ignores_other_methods():
    """channelMessage 以外は None を返す。"""
    msg = {"method": "auth", "params": {}}
    assert BitFlyerAdapter._normalize_order_event(msg) is None


@pytest.mark.unit
def test_normalize_ignores_other_channels():
    """child_order_events 以外のチャンネルは None を返す。"""
    msg = {
        "method": "channelMessage",
        "params": {"channel": "lightning_ticker_FX_BTC_JPY", "message": {}},
    }
    assert BitFlyerAdapter._normalize_order_event(msg) is None


# ------------------------------------------------------------------
# テスト: dry_run モード
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_place_order_dry_run_returns_order_id():
    """dry_run=True で API 呼び出しなし、ランダム order_id を返す。"""
    adapter = _adapter(dry_run=True)
    result = await adapter.place_order(
        client_order_id="test-1",
        side="BUY",
        type="market",
        size_jpy=100_000,
    )
    assert "order_id" in result
    assert result["order_id"].startswith("DRY-")


@pytest.mark.unit
async def test_cancel_order_dry_run_no_api():
    """dry_run=True で cancel_order が API を呼ばない。"""
    adapter = _adapter(dry_run=True)
    with patch("src.bitflyer_adapter.pybotters.Client") as mock_client:
        await adapter.cancel_order("JRF001")
    mock_client.assert_not_called()


@pytest.mark.unit
async def test_cancel_all_orders_dry_run_no_api():
    """dry_run=True で cancel_all_orders が API を呼ばない。"""
    adapter = _adapter(dry_run=True)
    with patch("src.bitflyer_adapter.pybotters.Client") as mock_client:
        await adapter.cancel_all_orders()
    mock_client.assert_not_called()


@pytest.mark.unit
async def test_get_account_snapshot_dry_run():
    """dry_run=True でゼロ埋めスナップショットを返す。"""
    adapter = _adapter(dry_run=True)
    snap = await adapter.get_account_snapshot()
    assert snap["daily_pnl_pct"] == 0.0
    assert snap["drawdown_pct"] == 0.0
    assert snap["positions"] == []


# ------------------------------------------------------------------
# テスト: place_order
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_place_order_market():
    """market 注文が sendchildorder に MARKET で送信される。"""
    adapter = _adapter()
    ticker_ctx = _make_resp_mock(TICKER_RESP)
    order_resp_ctx = _make_resp_mock({"child_order_acceptance_id": "JRF_MARKET_001"})

    client_ctx, client = _make_client_mock(post_resp=order_resp_ctx)

    with patch("src.bitflyer_adapter.pybotters.Client") as mock_cls:
        # _get_mid_price 用のクライアントと place_order 用のクライアントを順番に返す
        mock_cls.return_value = client_ctx
        client.get.return_value = ticker_ctx

        result = await adapter.place_order(
            client_order_id="test-market",
            side="BUY",
            type="market",
            size_jpy=100_000,
        )

    assert result["order_id"] == "JRF_MARKET_001"
    call_data = client.post.call_args.kwargs.get("data", {})
    assert call_data["child_order_type"] == "MARKET"
    assert call_data["side"] == "BUY"


@pytest.mark.unit
async def test_place_order_limit():
    """limit 注文が LIMIT type と price で送信される。"""
    adapter = _adapter()
    ticker_ctx = _make_resp_mock(TICKER_RESP)
    order_resp_ctx = _make_resp_mock({"child_order_acceptance_id": "JRF_LIMIT_001"})

    client_ctx, client = _make_client_mock(post_resp=order_resp_ctx)

    with patch("src.bitflyer_adapter.pybotters.Client") as mock_cls:
        mock_cls.return_value = client_ctx
        client.get.return_value = ticker_ctx

        result = await adapter.place_order(
            client_order_id="test-limit",
            side="SELL",
            type="limit",
            size_jpy=50_000,
            price=10_500_000.0,
        )

    assert result["order_id"] == "JRF_LIMIT_001"
    call_data = client.post.call_args.kwargs.get("data", {})
    assert call_data["child_order_type"] == "LIMIT"
    assert call_data["price"] == 10_500_000
    assert call_data["side"] == "SELL"


@pytest.mark.unit
async def test_place_order_ioc():
    """ioc 注文が MARKET + time_in_force=IOC で送信される。"""
    adapter = _adapter()
    ticker_ctx = _make_resp_mock(TICKER_RESP)
    order_resp_ctx = _make_resp_mock({"child_order_acceptance_id": "JRF_IOC_001"})

    client_ctx, client = _make_client_mock(post_resp=order_resp_ctx)

    with patch("src.bitflyer_adapter.pybotters.Client") as mock_cls:
        mock_cls.return_value = client_ctx
        client.get.return_value = ticker_ctx

        result = await adapter.place_order(
            client_order_id="test-ioc",
            side="BUY",
            type="ioc",
            size_jpy=100_000,
        )

    call_data = client.post.call_args.kwargs.get("data", {})
    assert call_data["child_order_type"] == "MARKET"
    assert call_data["time_in_force"] == "IOC"


@pytest.mark.unit
async def test_place_order_stop_market_registers_stop_watcher():
    """stop_market 注文が _StopWatcher に登録される。"""
    adapter = _adapter()

    with patch.object(adapter._stop_watcher, "register") as mock_register:
        with patch.object(adapter, "_ensure_stop_watcher", new_callable=AsyncMock):
            result = await adapter.place_order(
                client_order_id="test-stop",
                side="SELL",
                type="stop_market",
                size_jpy=100_000,
                stop_price=9_500_000.0,
            )

    mock_register.assert_called_once()
    stop_order = mock_register.call_args.args[0]
    assert stop_order.side == "SELL"
    assert stop_order.stop_price == 9_500_000.0
    assert "order_id" in result


@pytest.mark.unit
async def test_place_order_stop_market_without_stop_price_raises():
    """stop_market で stop_price なし → ValueError。"""
    adapter = _adapter()
    with pytest.raises(ValueError, match="stop_price"):
        await adapter.place_order(
            client_order_id="test",
            side="BUY",
            type="stop_market",
            size_jpy=100_000,
        )


@pytest.mark.unit
async def test_place_order_limit_without_price_raises():
    """limit で price なし → ValueError。"""
    adapter = _adapter()
    ticker_ctx = _make_resp_mock(TICKER_RESP)
    client_ctx, client = _make_client_mock()

    with patch("src.bitflyer_adapter.pybotters.Client") as mock_cls:
        mock_cls.return_value = client_ctx
        client.get.return_value = ticker_ctx

        with pytest.raises(ValueError, match="price"):
            await adapter.place_order(
                client_order_id="test",
                side="BUY",
                type="limit",
                size_jpy=100_000,
            )


# ------------------------------------------------------------------
# テスト: cancel_order / cancel_all_orders
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_cancel_order_calls_api():
    """cancel_order が cancelchildorder API を呼ぶ。"""
    adapter = _adapter()
    cancel_ctx = _make_resp_mock({})
    client_ctx, client = _make_client_mock(post_resp=cancel_ctx)

    with patch("src.bitflyer_adapter.pybotters.Client", return_value=client_ctx):
        await adapter.cancel_order("JRF_001")

    client.post.assert_called_once()
    url = client.post.call_args.args[0]
    assert "cancelchildorder" in url


@pytest.mark.unit
async def test_cancel_all_orders_calls_api():
    """cancel_all_orders が cancelallchildorders API を呼ぶ。"""
    adapter = _adapter()
    cancel_ctx = _make_resp_mock({})
    client_ctx, client = _make_client_mock(post_resp=cancel_ctx)

    with patch("src.bitflyer_adapter.pybotters.Client", return_value=client_ctx):
        await adapter.cancel_all_orders()

    client.post.assert_called_once()
    url = client.post.call_args.args[0]
    assert "cancelallchildorders" in url


# ------------------------------------------------------------------
# テスト: reduce_only バリデーション
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_reduce_only_raises_if_no_opposite_position():
    """reduce_only=True で反対ポジションなし → InvalidStateTransitionError。"""
    adapter = _adapter()
    # BUY 注文 reduce_only: SELL ポジションが必要だが存在しない
    positions = [{"side": "BUY", "size": 0.1, "price": 10_000_000.0}]

    with patch.object(adapter, "_get_positions", new_callable=AsyncMock, return_value=positions):
        with pytest.raises(InvalidStateTransitionError):
            await adapter.place_order(
                client_order_id="test",
                side="BUY",
                type="market",
                size_jpy=100_000,
                reduce_only=True,
            )


@pytest.mark.unit
async def test_reduce_only_passes_with_opposite_position():
    """reduce_only=True で反対ポジションあり → 正常に発注される。"""
    adapter = _adapter(dry_run=True)
    # BUY 注文 reduce_only: SELL ポジションが存在する
    positions = [{"side": "SELL", "size": 0.1, "price": 10_000_000.0}]

    with patch.object(adapter, "_get_positions", new_callable=AsyncMock, return_value=positions):
        result = await adapter.place_order(
            client_order_id="test",
            side="BUY",
            type="market",
            size_jpy=100_000,
            reduce_only=True,
        )

    assert "order_id" in result


# ------------------------------------------------------------------
# テスト: close_all_positions
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_close_all_positions_no_positions():
    """ポジションなしの場合は何もしない。"""
    adapter = _adapter(dry_run=True)
    with patch.object(adapter, "_get_positions", new_callable=AsyncMock, return_value=[]):
        await adapter.close_all_positions()  # 例外なし


@pytest.mark.unit
async def test_close_all_positions_slippage_exceeded():
    """スリッページが max_slippage_pct を超えると SlippageExceededError。"""
    adapter = _adapter()
    # entry_price = 10_000_000, mid_price = 10_300_000 → 3% ずれ → 2% 超過
    positions = [{"side": "BUY", "size": 0.1, "price": 10_000_000.0}]
    mid_price = 10_300_000.0

    with patch.object(adapter, "_get_positions", new_callable=AsyncMock, return_value=positions):
        with patch.object(adapter, "_get_mid_price", new_callable=AsyncMock, return_value=mid_price):
            with pytest.raises(SlippageExceededError):
                await adapter.close_all_positions(max_slippage_pct=2.0)


@pytest.mark.unit
async def test_close_all_positions_within_slippage():
    """スリッページが許容範囲内なら close_position が呼ばれる。"""
    adapter = _adapter()
    positions = [{"side": "BUY", "size": 0.1, "price": 10_000_000.0}]
    mid_price = 10_010_000.0  # 0.1% ずれ → 2% 以内

    with patch.object(adapter, "_get_positions", new_callable=AsyncMock, return_value=positions):
        with patch.object(adapter, "_get_mid_price", new_callable=AsyncMock, return_value=mid_price):
            with patch.object(adapter, "close_position", new_callable=AsyncMock) as mock_close:
                await adapter.close_all_positions(max_slippage_pct=2.0)

    mock_close.assert_called_once()
    kwargs = mock_close.call_args.kwargs
    assert kwargs["side"] == "SELL"  # BUY ポジションを SELL でクローズ


# ------------------------------------------------------------------
# テスト: get_account_snapshot
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_get_account_snapshot_daily_pnl():
    """daily_pnl_pct が equity の変化率として計算される。"""
    adapter = _adapter()
    collateral_data = {"collateral": 1_000_000.0, "open_position_pnl": 50_000.0}
    positions_data = []
    ticker_data = TICKER_RESP

    def make_get_resp(url, **kwargs):
        if "getcollateral" in url:
            return _make_resp_mock(collateral_data)
        elif "getpositions" in url:
            return _make_resp_mock(positions_data)
        else:
            return _make_resp_mock(ticker_data)

    client = MagicMock()
    client.get.side_effect = make_get_resp
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)

    # 初回呼び出し: equity_start_of_day が設定される
    with patch("src.bitflyer_adapter.pybotters.Client", return_value=client_ctx):
        snap1 = await adapter.get_account_snapshot()

    assert snap1["daily_pnl_pct"] == pytest.approx(0.0)

    # equity を増加させて再度呼び出し
    collateral_data["collateral"] = 1_100_000.0  # +10万 → +9.5%相当
    with patch("src.bitflyer_adapter.pybotters.Client", return_value=client_ctx):
        snap2 = await adapter.get_account_snapshot()

    # equity: 1_150_000 vs 1_050_000 → pnl > 0
    assert snap2["daily_pnl_pct"] > 0.0


@pytest.mark.unit
async def test_get_account_snapshot_hwm_drawdown():
    """HWM が更新され、下落時に drawdown_pct > 0 になる。"""
    adapter = _adapter()
    collateral_data = {"collateral": 1_000_000.0, "open_position_pnl": 0.0}
    ticker_data = TICKER_RESP

    def make_get_resp(url, **kwargs):
        if "getcollateral" in url:
            return _make_resp_mock(collateral_data)
        elif "getpositions" in url:
            return _make_resp_mock([])
        else:
            return _make_resp_mock(ticker_data)

    client = MagicMock()
    client.get.side_effect = make_get_resp
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)

    # 初回: HWM = 1_000_000
    with patch("src.bitflyer_adapter.pybotters.Client", return_value=client_ctx):
        await adapter.get_account_snapshot()

    # equity を増加 → HWM = 1_200_000
    collateral_data["collateral"] = 1_200_000.0
    with patch("src.bitflyer_adapter.pybotters.Client", return_value=client_ctx):
        await adapter.get_account_snapshot()

    # equity を減少 → drawdown 発生
    collateral_data["collateral"] = 1_080_000.0  # -10% from HWM
    with patch("src.bitflyer_adapter.pybotters.Client", return_value=client_ctx):
        snap = await adapter.get_account_snapshot()

    assert snap["drawdown_pct"] == pytest.approx(10.0, abs=0.1)


@pytest.mark.unit
async def test_get_account_snapshot_position_unrealized_pnl():
    """ポジションの unrealized_pnl_pct が正しく計算される。"""
    adapter = _adapter()
    collateral_data = {"collateral": 1_000_000.0, "open_position_pnl": 100_000.0}
    positions_data = [
        {"side": "BUY", "size": 0.1, "price": 9_000_000.0}
    ]
    # mid_price = 10_000_000 → BUY: (10M - 9M) / 9M * 100 ≈ 11.11%

    def make_get_resp(url, **kwargs):
        if "getcollateral" in url:
            return _make_resp_mock(collateral_data)
        elif "getpositions" in url:
            return _make_resp_mock(positions_data)
        else:
            return _make_resp_mock(TICKER_RESP)

    client = MagicMock()
    client.get.side_effect = make_get_resp
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.bitflyer_adapter.pybotters.Client", return_value=client_ctx):
        snap = await adapter.get_account_snapshot()

    assert len(snap["positions"]) == 1
    pos = snap["positions"][0]
    assert pos["unrealized_pnl_pct"] == pytest.approx(11.11, abs=0.1)


# ------------------------------------------------------------------
# テスト: _StopWatcher
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_stop_watcher_triggers_buy_stop():
    """BUY stop: current_price >= stop_price → place_order 呼び出し。"""
    adapter = _adapter(dry_run=True)
    stop_order = _StopOrder(
        order_id="sw-001",
        client_order_id="test-stop",
        side="BUY",
        stop_price=10_100_000.0,
        size_jpy=100_000,
        reduce_only=False,
    )
    adapter._stop_watcher.register(stop_order)

    # current_price = 10_200_000 → stop 条件達成
    with patch.object(
        adapter, "_get_mid_price", new_callable=AsyncMock, return_value=10_200_000.0
    ):
        with patch.object(adapter, "place_order", new_callable=AsyncMock) as mock_place:
            await adapter._stop_watcher._check_stops()

    mock_place.assert_called_once()
    kwargs = mock_place.call_args.kwargs
    assert kwargs["side"] == "BUY"
    assert kwargs["type"] == "market"


@pytest.mark.unit
async def test_stop_watcher_triggers_sell_stop():
    """SELL stop: current_price <= stop_price → place_order 呼び出し。"""
    adapter = _adapter(dry_run=True)
    stop_order = _StopOrder(
        order_id="sw-002",
        client_order_id="test-stop-sell",
        side="SELL",
        stop_price=9_800_000.0,
        size_jpy=100_000,
        reduce_only=False,
    )
    adapter._stop_watcher.register(stop_order)

    with patch.object(
        adapter, "_get_mid_price", new_callable=AsyncMock, return_value=9_700_000.0
    ):
        with patch.object(adapter, "place_order", new_callable=AsyncMock) as mock_place:
            await adapter._stop_watcher._check_stops()

    mock_place.assert_called_once()
    assert mock_place.call_args.kwargs["side"] == "SELL"


@pytest.mark.unit
async def test_stop_watcher_does_not_trigger_below_buy_stop():
    """BUY stop: current_price < stop_price → place_order 呼び出しなし。"""
    adapter = _adapter(dry_run=True)
    stop_order = _StopOrder(
        order_id="sw-003",
        client_order_id="test",
        side="BUY",
        stop_price=10_100_000.0,
        size_jpy=100_000,
        reduce_only=False,
    )
    adapter._stop_watcher.register(stop_order)

    with patch.object(
        adapter, "_get_mid_price", new_callable=AsyncMock, return_value=9_900_000.0
    ):
        with patch.object(adapter, "place_order", new_callable=AsyncMock) as mock_place:
            await adapter._stop_watcher._check_stops()

    mock_place.assert_not_called()


@pytest.mark.unit
async def test_stop_watcher_cancel_removes_order():
    """cancel() で stop 注文が削除される。"""
    adapter = _adapter()
    stop_order = _StopOrder(
        order_id="sw-cancel-001",
        client_order_id="test",
        side="BUY",
        stop_price=10_000_000.0,
        size_jpy=100_000,
        reduce_only=False,
    )
    adapter._stop_watcher.register(stop_order)
    assert "sw-cancel-001" in adapter._stop_watcher._orders

    await adapter._stop_watcher.cancel("sw-cancel-001")
    assert "sw-cancel-001" not in adapter._stop_watcher._orders


# ------------------------------------------------------------------
# テスト: user_data_stream (WebSocket)
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_user_data_stream_yields_normalized_event():
    """user_data_stream がキューから正規化イベントを yield する。"""
    adapter = _adapter()

    normalized_event = {
        "type": "ORDER_UPDATE",
        "data": {"order_id": "JRF001", "status": "FILLED"},
    }

    # _normalize_order_event が常に normalized_event を返すようにモック
    raw_msg = {"method": "channelMessage", "params": {"channel": "child_order_events", "message": {}}}

    client = MagicMock()

    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)

    async def fake_ws_connect(url, *, send_json, hdlr_json, **kwargs):
        # hdlr_json コールバックを通じてイベントを注入するタスクを起動
        async def _inject():
            await asyncio.sleep(0.01)
            hdlr_json(raw_msg)

        asyncio.create_task(_inject())

    client.ws_connect = fake_ws_connect

    with patch("src.bitflyer_adapter.pybotters.Client", return_value=client_ctx):
        with patch.object(
            BitFlyerAdapter,
            "_normalize_order_event",
            return_value=normalized_event,
        ):
            gen = adapter.user_data_stream()
            event = await gen.__anext__()

    assert event["type"] == "ORDER_UPDATE"
    assert event["data"]["order_id"] == "JRF001"

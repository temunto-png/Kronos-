"""
test_data_pipeline.py
BitFlyerDataPipeline のユニットテスト

実行:
    conda run -n kronos python -m pytest tests/test_data_pipeline.py -v
"""

import asyncio
import sys
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.data_pipeline import BitFlyerDataPipeline


# ------------------------------------------------------------------
# ヘルパー: HTTPレスポンスモック
# ------------------------------------------------------------------

def _make_resp_mock(json_data):
    """pybotters context manager レスポンスのモックを生成する。"""
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json = AsyncMock(return_value=json_data)

    # async context manager 対応
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


def _make_client_mock(**method_returns):
    """
    pybotters.Client の async context manager モックを生成する。

    method_returns: {"get": ctx_mock, "post": ctx_mock, ...}
    """
    client = MagicMock()
    for method, ctx in method_returns.items():
        getattr(client, method).return_value = ctx

    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)
    return client_ctx


def _make_executions(n: int, base_price: float = 10_000_000.0) -> list[dict]:
    """テスト用の約定履歴を生成する（昇順）。"""
    base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    execs = []
    for i in range(n):
        t = base_time + timedelta(minutes=i)
        execs.append({
            "id": 1000 + i,
            "side": "BUY" if i % 2 == 0 else "SELL",
            "price": base_price + i * 100,
            "size": 0.01,
            "exec_date": t.strftime("%Y-%m-%dT%H:%M:%S"),
            "buy_child_order_acceptance_id": f"JRF{i:08d}",
        })
    # bitFlyer は降順で返すため逆順にする
    return list(reversed(execs))


# ------------------------------------------------------------------
# テスト: _aggregate_ohlcv (純粋関数 → 非同期不要)
# ------------------------------------------------------------------

@pytest.mark.unit
def test_aggregate_ohlcv_1h_basic():
    """1h 足に集計できる。"""
    execs = _make_executions(120)  # 2時間分（1分ごと）
    df = BitFlyerDataPipeline._aggregate_ohlcv(execs, "1h")

    assert not df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "amount"]
    # 最初の1時間足: open < high, low <= open
    row = df.iloc[0]
    assert row["high"] >= row["open"]
    assert row["low"] <= row["open"]


@pytest.mark.unit
def test_aggregate_ohlcv_4h():
    """4h 足に集計できる。"""
    execs = _make_executions(300)  # 5時間分
    df = BitFlyerDataPipeline._aggregate_ohlcv(execs, "4h")

    assert not df.empty
    assert "amount" in df.columns


@pytest.mark.unit
def test_aggregate_ohlcv_1d():
    """1d 足に集計できる。"""
    # 25時間分
    base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    execs = []
    for i in range(25 * 60):
        t = base_time + timedelta(minutes=i)
        execs.append({
            "id": i,
            "side": "BUY",
            "price": 10_000_000.0,
            "size": 0.01,
            "exec_date": t.strftime("%Y-%m-%dT%H:%M:%S"),
            "buy_child_order_acceptance_id": f"JRF{i}",
        })
    df = BitFlyerDataPipeline._aggregate_ohlcv(list(reversed(execs)), "1d")
    assert len(df) >= 1


@pytest.mark.unit
def test_aggregate_ohlcv_amount_calculation():
    """amount = price * size で計算される。"""
    execs = [
        {
            "id": 1,
            "side": "BUY",
            "price": 10_000_000.0,
            "size": 0.5,
            "exec_date": "2024-01-01T00:30:00",
            "buy_child_order_acceptance_id": "JRF001",
        }
    ]
    df = BitFlyerDataPipeline._aggregate_ohlcv(execs, "1h")
    assert not df.empty
    expected_amount = 10_000_000.0 * 0.5
    assert abs(df.iloc[0]["amount"] - expected_amount) < 1.0


@pytest.mark.unit
def test_aggregate_ohlcv_empty():
    """空リスト → 空DataFrame を返す。"""
    df = BitFlyerDataPipeline._aggregate_ohlcv([], "1h")
    assert df.empty
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "amount"]


@pytest.mark.unit
def test_aggregate_ohlcv_index_is_utc():
    """index が UTC tz-aware DatetimeIndex である。"""
    execs = _make_executions(10)
    df = BitFlyerDataPipeline._aggregate_ohlcv(execs, "1h")
    assert df.index.tz is not None
    assert str(df.index.tz) == "UTC"


# ------------------------------------------------------------------
# テスト: get_ohlcv
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_get_ohlcv_returns_dataframe():
    """get_ohlcv() が DataFrame を返す。"""
    pipeline = BitFlyerDataPipeline()
    execs = _make_executions(200)

    client_ctx = _make_client_mock(get=_make_resp_mock(execs))

    with patch("src.data_pipeline.pybotters.Client", return_value=client_ctx):
        df = await pipeline.get_ohlcv(n_candles=2)

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "amount"]


@pytest.mark.unit
async def test_get_ohlcv_invalid_interval():
    """未対応の candle_interval → ValueError。"""
    pipeline = BitFlyerDataPipeline()
    with pytest.raises(ValueError, match="未対応の candle_interval"):
        await pipeline.get_ohlcv(candle_interval="5m")


@pytest.mark.unit
async def test_get_ohlcv_pagination():
    """n_candles > 500相当のデータが必要な場合にページングが発生する。"""
    pipeline = BitFlyerDataPipeline()

    # 1回目: 500件（古い時刻）
    now = datetime.now(timezone.utc)
    old_exec = {
        "id": 1,
        "side": "BUY",
        "price": 10_000_000.0,
        "size": 0.01,
        "exec_date": (now - timedelta(hours=1000)).strftime("%Y-%m-%dT%H:%M:%S"),
        "buy_child_order_acceptance_id": "JRF001",
    }
    page1 = [old_exec]  # 十分に古い → ループ終了

    client_ctx = _make_client_mock(get=_make_resp_mock(page1))

    call_count = 0

    async def mock_fetch(product_code, count=500, before=None):
        nonlocal call_count
        call_count += 1
        return page1

    with patch.object(pipeline, "_fetch_executions", side_effect=mock_fetch):
        df = await pipeline.get_ohlcv(n_candles=10)

    assert call_count >= 1


# ------------------------------------------------------------------
# テスト: get_current_funding_rate
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_get_current_funding_rate_success():
    """ファンディングレートを取得して deque に追記する。"""
    pipeline = BitFlyerDataPipeline()
    funding_data = {"current_funding_rate": 0.0001, "next_funding_rate_settlement_date": "..."}

    client_ctx = _make_client_mock(get=_make_resp_mock(funding_data))

    with patch("src.data_pipeline.pybotters.Client", return_value=client_ctx):
        rate = await pipeline.get_current_funding_rate()

    assert rate == pytest.approx(0.0001)
    assert len(pipeline._funding_history) == 1
    ts, r = pipeline._funding_history[0]
    assert r == pytest.approx(0.0001)


@pytest.mark.unit
async def test_get_current_funding_rate_appends_multiple():
    """複数回呼び出すと deque に複数エントリが積まれる。"""
    pipeline = BitFlyerDataPipeline()
    funding_data = {"current_funding_rate": 0.0002, "next_funding_rate_settlement_date": "..."}
    client_ctx = _make_client_mock(get=_make_resp_mock(funding_data))

    with patch("src.data_pipeline.pybotters.Client", return_value=client_ctx):
        await pipeline.get_current_funding_rate()
        await pipeline.get_current_funding_rate()

    assert len(pipeline._funding_history) == 2


# ------------------------------------------------------------------
# テスト: get_funding_rate_history
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_get_funding_rate_history_empty_deque_triggers_fetch():
    """deque が空のとき、即時フェッチしてから返す。"""
    pipeline = BitFlyerDataPipeline()
    funding_data = {"current_funding_rate": 0.0003, "next_funding_rate_settlement_date": "..."}
    client_ctx = _make_client_mock(get=_make_resp_mock(funding_data))

    with patch("src.data_pipeline.pybotters.Client", return_value=client_ctx):
        series = await pipeline.get_funding_rate_history(n_periods=10)

    assert isinstance(series, pd.Series)
    assert len(series) == 1
    assert series.iloc[0] == pytest.approx(0.0003)


@pytest.mark.unit
async def test_get_funding_rate_history_returns_series():
    """deque に蓄積済みのデータを返す。"""
    pipeline = BitFlyerDataPipeline()
    now = datetime.now(timezone.utc)
    pipeline._funding_history.append((now - timedelta(hours=2), 0.0001))
    pipeline._funding_history.append((now - timedelta(hours=1), 0.0002))
    pipeline._funding_history.append((now, 0.0003))

    series = await pipeline.get_funding_rate_history(n_periods=10)

    assert isinstance(series, pd.Series)
    assert len(series) == 3
    assert series.iloc[-1] == pytest.approx(0.0003)
    assert series.index.tz is not None


@pytest.mark.unit
async def test_get_funding_rate_history_n_periods_limit():
    """n_periods より多く蓄積されている場合、最新 n_periods 件を返す。"""
    pipeline = BitFlyerDataPipeline()
    now = datetime.now(timezone.utc)
    for i in range(10):
        pipeline._funding_history.append((now + timedelta(hours=i), float(i) * 0.0001))

    series = await pipeline.get_funding_rate_history(n_periods=3)
    assert len(series) == 3
    # 最新3件
    assert series.iloc[-1] == pytest.approx(9 * 0.0001)


# ------------------------------------------------------------------
# テスト: start() / stop()
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_start_creates_poll_task():
    """start() でポーリングタスクが起動する。"""
    pipeline = BitFlyerDataPipeline(funding_rate_poll_interval=9999)

    async def noop_poll():
        await asyncio.sleep(9999)

    with patch.object(pipeline, "_poll_funding_rate_forever", side_effect=noop_poll):
        await pipeline.start()
        assert pipeline._poll_task is not None
        assert not pipeline._poll_task.done()
        await pipeline.stop()

    assert pipeline._poll_task is None


@pytest.mark.unit
async def test_start_idempotent():
    """start() を2回呼んでもタスクが重複しない。"""
    pipeline = BitFlyerDataPipeline(funding_rate_poll_interval=9999)

    async def noop_poll():
        await asyncio.sleep(9999)

    with patch.object(pipeline, "_poll_funding_rate_forever", side_effect=noop_poll):
        await pipeline.start()
        task1 = pipeline._poll_task
        await pipeline.start()
        task2 = pipeline._poll_task

    assert task1 is task2
    await pipeline.stop()


@pytest.mark.unit
async def test_stop_cancels_task():
    """stop() でタスクがキャンセルされる。"""
    pipeline = BitFlyerDataPipeline(funding_rate_poll_interval=9999)

    async def noop_poll():
        await asyncio.sleep(9999)

    with patch.object(pipeline, "_poll_funding_rate_forever", side_effect=noop_poll):
        await pipeline.start()
        await pipeline.stop()

    assert pipeline._poll_task is None


# ------------------------------------------------------------------
# テスト: _fetch_executions
# ------------------------------------------------------------------

@pytest.mark.unit
async def test_fetch_executions_no_before():
    """before なしで GET が呼ばれる。"""
    pipeline = BitFlyerDataPipeline()
    execs = _make_executions(5)

    resp_ctx = _make_resp_mock(execs)
    client = MagicMock()
    client.get.return_value = resp_ctx
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.data_pipeline.pybotters.Client", return_value=client_ctx):
        result = await pipeline._fetch_executions("FX_BTC_JPY", count=500)

    assert result == execs
    call_kwargs = client.get.call_args
    assert "before" not in call_kwargs.kwargs.get("params", {})


@pytest.mark.unit
async def test_fetch_executions_with_before():
    """before あり で params に before が含まれる。"""
    pipeline = BitFlyerDataPipeline()
    execs = _make_executions(3)

    resp_ctx = _make_resp_mock(execs)
    client = MagicMock()
    client.get.return_value = resp_ctx
    client_ctx = MagicMock()
    client_ctx.__aenter__ = AsyncMock(return_value=client)
    client_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("src.data_pipeline.pybotters.Client", return_value=client_ctx):
        await pipeline._fetch_executions("FX_BTC_JPY", count=500, before=9999)

    params = client.get.call_args.kwargs.get("params", {})
    assert params.get("before") == "9999"

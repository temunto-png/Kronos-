"""
data_pipeline.py
bitFlyer Lightning Crypto CFD の OHLCV データと
ファンディングレート履歴を提供するパイプライン。

設計原則: 「計算はPython、判断はLLM」
- 全メソッドが async
- ファンディングレートは定期ポーリングで deque に蓄積（履歴 API なし）
- OHLCV は /v1/getexecutions から集計（外部依存なし）
"""

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import pandas as pd
import pybotters

logger = logging.getLogger("kronos.data_pipeline")

_BASE_URL = "https://api.bitflyer.com"
_EXEC_URL = f"{_BASE_URL}/v1/getexecutions"
_FUNDING_URL = f"{_BASE_URL}/v1/getfundingrate"

# bitFlyer レート制限: 200 req/min（非認証）→ 0.3 秒間隔
_REQUEST_INTERVAL = 0.3

_CANDLE_INTERVAL_MAP = {
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}


class BitFlyerDataPipeline:
    """
    bitFlyer Lightning の約定履歴から OHLCV を集計し、
    ファンディングレート履歴を定期ポーリングして提供するパイプライン。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        funding_rate_poll_interval: int = 3600,
        funding_rate_history_len: int = 200,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._funding_rate_poll_interval = funding_rate_poll_interval
        self._funding_history: deque[tuple[datetime, float]] = deque(
            maxlen=funding_rate_history_len
        )
        self._poll_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """ファンディングレート定期ポーリングを開始する。"""
        if self._poll_task is not None and not self._poll_task.done():
            return
        self._poll_task = asyncio.create_task(self._poll_funding_rate_forever())
        logger.info("ファンディングレートポーリング開始 (間隔=%ds)", self._funding_rate_poll_interval)

    async def stop(self) -> None:
        """ポーリングタスクを停止する。"""
        if self._poll_task is not None and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            logger.info("ファンディングレートポーリング停止")
        self._poll_task = None

    async def get_ohlcv(
        self,
        product_code: str = "FX_BTC_JPY",
        candle_interval: str = "1h",
        n_candles: int = 512,
    ) -> pd.DataFrame:
        """
        OHLCV DataFrame を返す。

        columns: open, high, low, close, volume, amount
        index: DatetimeIndex (UTC, tz-aware)
        amount = price * size (JPY建て出来高)
        """
        if candle_interval not in _CANDLE_INTERVAL_MAP:
            raise ValueError(
                f"未対応の candle_interval: '{candle_interval}'。"
                f"サポート: {list(_CANDLE_INTERVAL_MAP.keys())}"
            )
        executions = await self._paginate_to_cover(product_code, candle_interval, n_candles)
        df = self._aggregate_ohlcv(executions, candle_interval)
        return df.tail(n_candles)

    async def get_funding_rate_history(
        self,
        n_periods: int = 100,
    ) -> pd.Series:
        """
        直近 n_periods 件のファンディングレート履歴を返す。

        index: DatetimeIndex (UTC, tz-aware), value: funding_rate (float)
        deque が空の場合は1回即時フェッチしてから返す。
        """
        if len(self._funding_history) == 0:
            await self.get_current_funding_rate()

        history = list(self._funding_history)[-n_periods:]
        timestamps = [ts for ts, _ in history]
        rates = [r for _, r in history]

        index = pd.DatetimeIndex(timestamps)
        if index.tz is None:
            index = index.tz_localize("UTC")

        return pd.Series(rates, index=index, name="funding_rate", dtype=float)

    async def get_current_funding_rate(self) -> float:
        """現在のファンディングレートを取得し deque に追記して返す。"""
        apis: dict = {}
        if self._api_key and self._api_secret:
            apis = {"bitflyer": [self._api_key, self._api_secret]}

        async with pybotters.Client(apis=apis) as client:
            async with client.get(
                _FUNDING_URL,
                params={"product_code": "FX_BTC_JPY"},
                auth=None,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        rate = float(data["current_funding_rate"])
        now_utc = datetime.now(timezone.utc)
        self._funding_history.append((now_utc, rate))
        logger.debug("ファンディングレート取得: %.6f", rate)
        return rate

    # ------------------------------------------------------------------
    # 内部メソッド
    # ------------------------------------------------------------------

    async def _fetch_executions(
        self,
        product_code: str,
        count: int = 500,
        before: Optional[int] = None,
    ) -> list[dict]:
        """GET /v1/getexecutions から1ページ取得する（降順）。"""
        params: dict = {"product_code": product_code, "count": str(count)}
        if before is not None:
            params["before"] = str(before)

        async with pybotters.Client(apis={}) as client:
            async with client.get(_EXEC_URL, params=params, auth=None) as resp:
                resp.raise_for_status()
                data = await resp.json()

        return data

    @staticmethod
    def _aggregate_ohlcv(
        executions: list[dict],
        candle_interval: str,
    ) -> pd.DataFrame:
        """
        約定履歴リスト → OHLCV DataFrame に集計する。

        executions は降順（新しい順）でも昇順でも動作する。
        """
        if not executions:
            return pd.DataFrame(
                columns=["open", "high", "low", "close", "volume", "amount"]
            )

        freq = _CANDLE_INTERVAL_MAP[candle_interval]

        df = pd.DataFrame(executions)
        df["exec_date"] = pd.to_datetime(df["exec_date"], utc=True)
        df["price"] = df["price"].astype(float)
        df["size"] = df["size"].astype(float)
        df["amount"] = df["price"] * df["size"]

        df = df.sort_values("exec_date")
        df = df.set_index("exec_date")

        ohlcv = df["price"].resample(freq).ohlc()
        ohlcv["volume"] = df["size"].resample(freq).sum()
        ohlcv["amount"] = df["amount"].resample(freq).sum()

        # 約定なし足を除去
        ohlcv = ohlcv.dropna(subset=["open"])
        return ohlcv

    async def _paginate_to_cover(
        self,
        product_code: str,
        candle_interval: str,
        n_candles: int,
    ) -> list[dict]:
        """
        n_candles 本をカバーするために必要な約定履歴をページングして収集する。
        """
        candle_seconds = {"1h": 3600, "4h": 14400, "1d": 86400}
        interval_sec = candle_seconds.get(candle_interval, 3600)

        # 目標期間（秒）: n_candles * interval * マージン 1.3
        target_seconds = int(n_candles * interval_sec * 1.3)

        all_executions: list[dict] = []
        before: Optional[int] = None
        oldest_needed = datetime.now(timezone.utc).timestamp() - target_seconds

        while True:
            page = await self._fetch_executions(product_code, count=500, before=before)
            if not page:
                break

            all_executions.extend(page)
            await asyncio.sleep(_REQUEST_INTERVAL)

            # descending order: page[-1] が最古
            oldest_exec = page[-1]
            oldest_dt = pd.Timestamp(oldest_exec["exec_date"], tz="UTC")

            if oldest_dt.timestamp() <= oldest_needed:
                break

            before = oldest_exec["id"]

        return all_executions

    async def _poll_funding_rate_forever(self) -> None:
        """ファンディングレートを定期ポーリングして deque に蓄積する。"""
        while True:
            try:
                await self.get_current_funding_rate()
            except Exception as exc:
                logger.warning("ファンディングレートポーリング失敗: %s", exc)
            await asyncio.sleep(self._funding_rate_poll_interval)

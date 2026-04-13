"""
kronos_bridge.py
Kronosモデルの predict_batch() 出力を kronos_preprocessor.preprocess() が
期待する kronos_forecast dict 形式に変換するアダプター。

設計原則: 「計算はPython、判断はLLM」
- ここで行うのは形式変換のみ
- n_paths 本の独立した確率的パスを生成し、統計計算は preprocessor に委譲

使い方:
    bridge = KronosBridge(predictor, candle_interval="1h")
    kronos_forecast = bridge.forecast(
        df=ohlcv_df,
        x_timestamp=x_ts,
        y_timestamp=y_ts,
        pred_len=24,
    )
    result = preprocess(historical_klines, kronos_forecast, ...)
"""

import logging
import sys
import os
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "kronos_model"))
from model import KronosPredictor  # noqa: E402

logger = logging.getLogger("kronos.bridge")

# デフォルト設定
DEFAULT_N_PATHS = 20
DEFAULT_TEMPERATURE = 1.0
DEFAULT_TOP_P = 0.9


class KronosBridge:
    """
    KronosPredictor と kronos_preprocessor の間の変換アダプター。

    predict_batch() を使って n_paths 本の独立した確率的パスを並列生成し、
    preprocessor が消費できる kronos_forecast dict に整形して返す。
    """

    def __init__(
        self,
        predictor: KronosPredictor,
        candle_interval: str = "1h",
    ) -> None:
        """
        Args:
            predictor: ロード済みの KronosPredictor インスタンス
            candle_interval: ローソク足の時間軸。"1h" / "4h" / "1d"
        """
        self.predictor = predictor
        self.candle_interval = candle_interval

    def forecast(
        self,
        df: pd.DataFrame,
        x_timestamp: pd.Series,
        y_timestamp: pd.Series,
        pred_len: int,
        n_paths: int = DEFAULT_N_PATHS,
        temperature: float = DEFAULT_TEMPERATURE,
        top_p: float = DEFAULT_TOP_P,
        verbose: bool = False,
    ) -> dict:
        """
        Kronos で n_paths 本の確率的パスを生成し、kronos_forecast dict を返す。

        predict_batch() に同一 df を n_paths 個並べ、sample_count=1 で呼ぶことで
        モデルのサンプリング（torch.multinomial）の確率性を利用して独立パスを得る。

        Args:
            df: 入力 OHLCV DataFrame (open/high/low/close 必須、volume/amount は省略可)
            x_timestamp: df と同長の pd.Series[Timestamp]
            y_timestamp: 予測対象期間の pd.Series[Timestamp]（length == pred_len）
            pred_len: 予測ステップ数
            n_paths: 生成する確率的パス本数（推奨: 20 以上）
            temperature: サンプリング温度（高いほど多様性が増す）
            top_p: Nucleus sampling の閾値
            verbose: tqdm 表示フラグ

        Returns:
            kronos_forecast dict::
                {
                    "meta": {
                        "candle_interval": str,
                        "temperature": float,
                        "top_p": float,
                    },
                    "paths": [
                        # n_paths 本のパス。各パスは pred_len 個のローソク足 dict のリスト
                        [
                            {"open": float, "high": float, "low": float,
                             "close": float, "volume": float, "amount": float},
                            ...
                        ],
                        ...
                    ]
                }

        Raises:
            ValueError: df カラム不足 / y_timestamp 長さ不一致
        """
        self._validate_inputs(df, x_timestamp, y_timestamp, pred_len, n_paths)

        logger.info(
            "forecast start | interval=%s | pred_len=%d | n_paths=%d | T=%.2f | top_p=%.2f",
            self.candle_interval, pred_len, n_paths, temperature, top_p,
        )

        # n_paths 本分の同一データを複製して並列推論
        df_list = [df] * n_paths
        x_ts_list = [x_timestamp] * n_paths
        y_ts_list = [y_timestamp] * n_paths

        pred_df_list: list[pd.DataFrame] = self.predictor.predict_batch(
            df_list=df_list,
            x_timestamp_list=x_ts_list,
            y_timestamp_list=y_ts_list,
            pred_len=pred_len,
            T=temperature,
            top_k=0,
            top_p=top_p,
            sample_count=1,   # 内部平均させず、1パスずつ独立生成
            verbose=verbose,
        )

        paths = self._pred_df_list_to_paths(pred_df_list)

        kronos_forecast = {
            "meta": {
                "candle_interval": self.candle_interval,
                "temperature": temperature,
                "top_p": top_p,
            },
            "paths": paths,
        }

        logger.info(
            "forecast done | paths=%d | horizon=%d candles",
            len(paths), pred_len,
        )
        return kronos_forecast

    # ------------------------------------------------------------------
    # private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_inputs(
        df: pd.DataFrame,
        x_timestamp: pd.Series,
        y_timestamp: pd.Series,
        pred_len: int,
        n_paths: int,
    ) -> None:
        required_cols = {"open", "high", "low", "close"}
        missing = required_cols - set(df.columns)
        if missing:
            raise ValueError(f"df に必須カラムが不足: {missing}")

        if len(df) != len(x_timestamp):
            raise ValueError(
                f"df 行数 ({len(df)}) と x_timestamp 長さ ({len(x_timestamp)}) が不一致"
            )

        if len(y_timestamp) != pred_len:
            raise ValueError(
                f"y_timestamp 長さ ({len(y_timestamp)}) が pred_len ({pred_len}) と不一致"
            )

        if n_paths < 1:
            raise ValueError(f"n_paths は 1 以上が必要: {n_paths}")

        if n_paths < 5:
            logger.warning(
                "n_paths=%d は少なすぎる。統計的信頼性のため 20 以上を推奨", n_paths
            )

    @staticmethod
    def _pred_df_list_to_paths(pred_df_list: list[pd.DataFrame]) -> list[list[dict]]:
        """
        List[pd.DataFrame] → preprocessor が期待する paths 形式に変換。

        各 DataFrame の各行を {"open", "high", "low", "close", "volume", "amount"} の
        dict に変換する。volume / amount が存在しない場合は 0.0 で補完。
        """
        paths = []
        for pred_df in pred_df_list:
            path = []
            has_volume = "volume" in pred_df.columns
            has_amount = "amount" in pred_df.columns
            for _, row in pred_df.iterrows():
                candle = {
                    "open":   float(row["open"]),
                    "high":   float(row["high"]),
                    "low":    float(row["low"]),
                    "close":  float(row["close"]),
                    "volume": float(row["volume"]) if has_volume else 0.0,
                    "amount": float(row["amount"]) if has_amount else 0.0,
                }
                path.append(candle)
            paths.append(path)
        return paths


def build_y_timestamp(
    last_x_timestamp: pd.Timestamp,
    pred_len: int,
    candle_interval: str,
) -> pd.Series:
    """
    x_timestamp の末尾から pred_len 本分の予測タイムスタンプを生成するユーティリティ。

    Args:
        last_x_timestamp: 入力系列の最後のタイムスタンプ
        pred_len: 予測ステップ数
        candle_interval: "1h" / "4h" / "1d"

    Returns:
        pd.Series[Timestamp] （length == pred_len）
    """
    freq_map = {"1h": "1h", "4h": "4h", "1d": "1D"}
    freq = freq_map.get(candle_interval)
    if freq is None:
        raise ValueError(
            f"未対応の candle_interval: '{candle_interval}'。"
            f"サポート: {list(freq_map.keys())}"
        )
    timestamps = pd.date_range(
        start=last_x_timestamp + pd.Timedelta(freq),
        periods=pred_len,
        freq=freq,
    )
    return pd.Series(timestamps)

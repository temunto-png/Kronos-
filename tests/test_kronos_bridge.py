"""
test_kronos_bridge.py
KronosBridge のユニットテスト

テスト区分:
  - Unit: モックを使った高速テスト（GPU 不要）
  - Integration: 実モデルを使った結合テスト（GPU / HF ダウンロード必要）

実行:
    # Unit のみ（高速）
    python -m pytest tests/test_kronos_bridge.py -m "not integration" -v

    # 全テスト（実モデル使用）
    python -m pytest tests/test_kronos_bridge.py -v
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "kronos_model"))

import pytest
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch

from src.kronos_bridge import KronosBridge, build_y_timestamp


# ============================================================
# フィクスチャ
# ============================================================

def make_ohlcv_df(n_rows: int = 400, base_price: float = 10_000_000.0) -> pd.DataFrame:
    """合成 OHLCV DataFrame を生成"""
    rng = np.random.default_rng(42)
    closes = base_price + rng.normal(0, base_price * 0.001, n_rows).cumsum()
    opens = closes + rng.normal(0, base_price * 0.0005, n_rows)
    highs = np.maximum(opens, closes) + abs(rng.normal(0, base_price * 0.0003, n_rows))
    lows = np.minimum(opens, closes) - abs(rng.normal(0, base_price * 0.0003, n_rows))
    volumes = rng.uniform(100, 1000, n_rows)
    amounts = volumes * closes

    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "amount": amounts,
    })


def make_timestamps(n: int, freq: str = "1h") -> pd.Series:
    return pd.Series(pd.date_range("2024-01-01", periods=n, freq=freq))


def make_mock_predictor(pred_len: int, n_paths: int, base_price: float = 10_000_000.0):
    """predict_batch の戻り値をモックする KronosPredictor"""
    rng = np.random.default_rng(99)

    def mock_predict_batch(df_list, x_timestamp_list, y_timestamp_list, pred_len, **kwargs):
        results = []
        for y_ts in y_timestamp_list:
            closes = base_price + rng.normal(0, base_price * 0.001, pred_len).cumsum()
            highs = closes + abs(rng.normal(0, base_price * 0.0002, pred_len))
            lows = closes - abs(rng.normal(0, base_price * 0.0002, pred_len))
            df = pd.DataFrame({
                "open": closes + rng.normal(0, base_price * 0.0001, pred_len),
                "high": highs,
                "low": lows,
                "close": closes,
                "volume": rng.uniform(50, 500, pred_len),
                "amount": closes * rng.uniform(50, 500, pred_len),
            }, index=y_ts)
            results.append(df)
        return results

    predictor = MagicMock()
    predictor.predict_batch.side_effect = mock_predict_batch
    return predictor


# ============================================================
# Unit テスト
# ============================================================

class TestKronosBridgeUnit:

    def setup_method(self):
        self.pred_len = 24
        self.n_paths = 5
        self.df = make_ohlcv_df(400)
        self.x_ts = make_timestamps(400, "1h")
        self.y_ts = make_timestamps(self.pred_len, "1h")
        self.mock_predictor = make_mock_predictor(self.pred_len, self.n_paths)
        self.bridge = KronosBridge(self.mock_predictor, candle_interval="1h")

    def test_forecast_returns_valid_structure(self):
        """kronos_forecast dict が正しい構造を持つこと"""
        result = self.bridge.forecast(
            df=self.df,
            x_timestamp=self.x_ts,
            y_timestamp=self.y_ts,
            pred_len=self.pred_len,
            n_paths=self.n_paths,
        )

        assert "meta" in result
        assert "paths" in result

        meta = result["meta"]
        assert meta["candle_interval"] == "1h"
        assert isinstance(meta["temperature"], float)
        assert isinstance(meta["top_p"], float)

    def test_forecast_paths_count(self):
        """paths の本数が n_paths と一致すること"""
        result = self.bridge.forecast(
            df=self.df,
            x_timestamp=self.x_ts,
            y_timestamp=self.y_ts,
            pred_len=self.pred_len,
            n_paths=self.n_paths,
        )
        assert len(result["paths"]) == self.n_paths

    def test_forecast_path_length(self):
        """各パスのローソク足数が pred_len と一致すること"""
        result = self.bridge.forecast(
            df=self.df,
            x_timestamp=self.x_ts,
            y_timestamp=self.y_ts,
            pred_len=self.pred_len,
            n_paths=self.n_paths,
        )
        for path in result["paths"]:
            assert len(path) == self.pred_len

    def test_forecast_candle_keys(self):
        """各ローソク足 dict が必須キーを持つこと"""
        result = self.bridge.forecast(
            df=self.df,
            x_timestamp=self.x_ts,
            y_timestamp=self.y_ts,
            pred_len=self.pred_len,
            n_paths=self.n_paths,
        )
        required = {"open", "high", "low", "close", "volume", "amount"}
        for path in result["paths"]:
            for candle in path:
                assert set(candle.keys()) == required

    def test_forecast_candle_values_are_float(self):
        """ローソク足の各値が float であること"""
        result = self.bridge.forecast(
            df=self.df,
            x_timestamp=self.x_ts,
            y_timestamp=self.y_ts,
            pred_len=self.pred_len,
            n_paths=self.n_paths,
        )
        for path in result["paths"]:
            for candle in path:
                for key, val in candle.items():
                    assert isinstance(val, float), f"{key} is not float: {type(val)}"

    def test_forecast_calls_predict_batch_with_correct_list_length(self):
        """predict_batch に n_paths 個の df が渡されること"""
        self.bridge.forecast(
            df=self.df,
            x_timestamp=self.x_ts,
            y_timestamp=self.y_ts,
            pred_len=self.pred_len,
            n_paths=self.n_paths,
        )
        call_args = self.mock_predictor.predict_batch.call_args
        assert len(call_args.kwargs["df_list"]) == self.n_paths

    def test_forecast_calls_predict_batch_with_sample_count_1(self):
        """predict_batch には sample_count=1 で呼ばれること（内部平均させない）"""
        self.bridge.forecast(
            df=self.df,
            x_timestamp=self.x_ts,
            y_timestamp=self.y_ts,
            pred_len=self.pred_len,
            n_paths=self.n_paths,
        )
        call_args = self.mock_predictor.predict_batch.call_args
        assert call_args.kwargs.get("sample_count") == 1

    def test_validate_missing_price_columns(self):
        """必須カラム欠損時に ValueError が発生すること"""
        bad_df = self.df.drop(columns=["close"])
        with pytest.raises(ValueError, match="必須カラムが不足"):
            self.bridge.forecast(
                df=bad_df,
                x_timestamp=self.x_ts,
                y_timestamp=self.y_ts,
                pred_len=self.pred_len,
                n_paths=self.n_paths,
            )

    def test_validate_length_mismatch_x_timestamp(self):
        """x_timestamp の長さ不一致で ValueError が発生すること"""
        bad_ts = make_timestamps(100, "1h")  # df は 400 行
        with pytest.raises(ValueError, match="x_timestamp 長さ"):
            self.bridge.forecast(
                df=self.df,
                x_timestamp=bad_ts,
                y_timestamp=self.y_ts,
                pred_len=self.pred_len,
                n_paths=self.n_paths,
            )

    def test_validate_y_timestamp_pred_len_mismatch(self):
        """y_timestamp の長さが pred_len と不一致で ValueError が発生すること"""
        bad_y_ts = make_timestamps(10, "1h")  # pred_len=24 と不一致
        with pytest.raises(ValueError, match="y_timestamp 長さ"):
            self.bridge.forecast(
                df=self.df,
                x_timestamp=self.x_ts,
                y_timestamp=bad_y_ts,
                pred_len=self.pred_len,
                n_paths=self.n_paths,
            )

    def test_validate_n_paths_zero(self):
        """n_paths=0 で ValueError が発生すること"""
        with pytest.raises(ValueError, match="n_paths は 1 以上"):
            self.bridge.forecast(
                df=self.df,
                x_timestamp=self.x_ts,
                y_timestamp=self.y_ts,
                pred_len=self.pred_len,
                n_paths=0,
            )

    def test_forecast_without_volume_columns(self):
        """volume/amount なし df でも 0.0 補完して正常動作すること"""
        df_no_vol = self.df[["open", "high", "low", "close"]].copy()

        # volume/amount なしの DF を返すようにモックを調整
        def mock_no_vol(df_list, x_timestamp_list, y_timestamp_list, pred_len, **kwargs):
            rng = np.random.default_rng(1)
            results = []
            for y_ts in y_timestamp_list:
                closes = 10_000_000.0 + rng.normal(0, 1000, pred_len).cumsum()
                df = pd.DataFrame({
                    "open": closes,
                    "high": closes + 500,
                    "low": closes - 500,
                    "close": closes,
                    # volume / amount なし
                }, index=y_ts)
                results.append(df)
            return results

        predictor = MagicMock()
        predictor.predict_batch.side_effect = mock_no_vol
        bridge = KronosBridge(predictor, candle_interval="1h")

        result = bridge.forecast(
            df=df_no_vol,
            x_timestamp=self.x_ts,
            y_timestamp=self.y_ts,
            pred_len=self.pred_len,
            n_paths=3,
        )
        for path in result["paths"]:
            for candle in path:
                assert candle["volume"] == 0.0
                assert candle["amount"] == 0.0

    def test_meta_reflects_parameters(self):
        """meta に渡したパラメータが正しく反映されること"""
        result = self.bridge.forecast(
            df=self.df,
            x_timestamp=self.x_ts,
            y_timestamp=self.y_ts,
            pred_len=self.pred_len,
            n_paths=self.n_paths,
            temperature=0.8,
            top_p=0.95,
        )
        assert result["meta"]["temperature"] == 0.8
        assert result["meta"]["top_p"] == 0.95
        assert result["meta"]["candle_interval"] == "1h"


# ============================================================
# build_y_timestamp テスト
# ============================================================

class TestBuildYTimestamp:

    def test_1h_generates_correct_length(self):
        last_ts = pd.Timestamp("2024-06-01 12:00:00")
        y_ts = build_y_timestamp(last_ts, pred_len=24, candle_interval="1h")
        assert len(y_ts) == 24

    def test_1h_first_timestamp_is_next_candle(self):
        last_ts = pd.Timestamp("2024-06-01 12:00:00")
        y_ts = build_y_timestamp(last_ts, pred_len=24, candle_interval="1h")
        assert y_ts.iloc[0] == pd.Timestamp("2024-06-01 13:00:00")

    def test_4h_interval(self):
        last_ts = pd.Timestamp("2024-06-01 08:00:00")
        y_ts = build_y_timestamp(last_ts, pred_len=6, candle_interval="4h")
        assert len(y_ts) == 6
        assert y_ts.iloc[0] == pd.Timestamp("2024-06-01 12:00:00")

    def test_1d_interval(self):
        last_ts = pd.Timestamp("2024-06-01 00:00:00")
        y_ts = build_y_timestamp(last_ts, pred_len=7, candle_interval="1d")
        assert len(y_ts) == 7
        assert y_ts.iloc[0] == pd.Timestamp("2024-06-02 00:00:00")

    def test_unsupported_interval_raises(self):
        with pytest.raises(ValueError, match="未対応の candle_interval"):
            build_y_timestamp(pd.Timestamp("2024-01-01"), pred_len=10, candle_interval="5m")


# ============================================================
# Integration テスト（実モデル使用）
# ============================================================

@pytest.mark.integration
class TestKronosBridgeIntegration:
    """実際の Kronos-small モデルを使った結合テスト"""

    @pytest.fixture(scope="class")
    def predictor(self):
        from model import Kronos, KronosTokenizer, KronosPredictor
        tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
        model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
        return KronosPredictor(model, tokenizer, max_context=512)

    def test_real_forecast_structure(self, predictor):
        pred_len = 12
        n_paths = 5  # 速度優先で少なめ

        df = make_ohlcv_df(400)
        x_ts = make_timestamps(400, "1h")
        y_ts = make_timestamps(pred_len, "1h")

        bridge = KronosBridge(predictor, candle_interval="1h")
        result = bridge.forecast(
            df=df,
            x_timestamp=x_ts,
            y_timestamp=y_ts,
            pred_len=pred_len,
            n_paths=n_paths,
            verbose=False,
        )

        assert len(result["paths"]) == n_paths
        for path in result["paths"]:
            assert len(path) == pred_len
            for candle in path:
                assert "close" in candle
                assert candle["close"] > 0

    def test_paths_are_stochastic(self, predictor):
        """同じ入力でも各パスが異なる（確率的であること）"""
        pred_len = 6
        n_paths = 5

        df = make_ohlcv_df(400)
        x_ts = make_timestamps(400, "1h")
        y_ts = make_timestamps(pred_len, "1h")

        bridge = KronosBridge(predictor, candle_interval="1h")
        result = bridge.forecast(
            df=df,
            x_timestamp=x_ts,
            y_timestamp=y_ts,
            pred_len=pred_len,
            n_paths=n_paths,
            verbose=False,
        )

        final_closes = [path[-1]["close"] for path in result["paths"]]
        # 全パスが完全一致ではないこと（確率的生成の確認）
        assert len(set(round(c, 2) for c in final_closes)) > 1, (
            "全パスが同一の close を持つ（確率的サンプリングが機能していない可能性）"
        )

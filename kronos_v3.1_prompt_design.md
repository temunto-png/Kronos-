# Kronos Trading Decision Engine v3.1 — プロンプト設計書

**設計日:** 2026年4月12日（v3.1）/ 2026年4月13日（v3.1.1）  
**前版:** v3.0 → v3.1 → v3.1.1 → v3.1.2  
**変更理由:** v3.1: 4職種クロスレビュー / v3.1.1: Gemini・Codex敵対的レビュー反映 / v3.1.2: 残課題対応  
**設計原則:** 「計算はPython、判断はLLM」の完全分離（v3.0を継承）

---

## 目次

1. [v3.0→v3.1 修正一覧](#1-v30v31-修正一覧)
2. [Python前処理レイヤー仕様](#2-python前処理レイヤー仕様)
3. [System Prompt v3.1（本体）](#3-system-prompt-v31本体)
4. [エッジケーステスト仕様](#4-エッジケーステスト仕様)
5. [バックテスト統合ガイド](#5-バックテスト統合ガイド)
6. [執行レイヤー仕様（v3.1新規）](#6-執行レイヤー仕様v31新規)
7. [リアルタイム監視プロセス仕様（v3.1新規）](#7-リアルタイム監視プロセス仕様v31新規)

---

## 1. v3.0→v3.1 修正一覧

### P0（致命的修正）

| ID | 問題 | 修正内容 |
|---|---|---|
| C1 | Kelly式の数学的誤り | 正規Kelly `f* = (p*b - q) / b` に修正。b = gain/loss比 |
| C7 | LLM非決定性によるバックテスト不能 | バックテスト時はルールベースフォールバックを使用。本番判断のみLLM |
| C9 | サーキットブレーカーが判断サイクル間でバイパスされる | 独立リアルタイム監視プロセスを新設（セクション7） |

### P1（重大修正）

| ID | 問題 | 修正内容 |
|---|---|---|
| C2 | WIN_RATE_LOOKUPが3段階離散値 | ロジスティック回帰による連続関数化 |
| C3 | ADX proxyがCVでありトレンド方向性を測定できない | 線形回帰R² + 回帰勾配符号に変更 |
| C4 | レジーム判定が3点比較で脆弱 | R² + 回帰勾配 + ボラティリティの複合判定に変更 |
| C5 | スリッページ固定0.02% | bid-ask spread連動 + 時間帯・サイズ補正 |
| C6 | TP/SLが同距離でR:R=1:1 | 勝率連動の非対称R:R |
| C8 | JSON parse失敗時のハンドリング不足 | Pydanticバリデーション追加 |
| C10 | FORCE_CLOSEの執行アルゴ未定義 | 許容スリッページ上限付きIOC注文 |

### P2（改善）

| ID | 問題 | 修正内容 |
|---|---|---|
| M1 | Kelly計算にmeanを使用 | medianベースに切り替え |
| M3 | WEAK_BUYの指値オフセット固定 | ATR連動可変オフセット |
| M4 | time-stopの執行主体が不明 | 執行レイヤー仕様に明記 |
| M5 | TP1後のSL移動が未定義 | TP1ヒット時にSLを建値に移動と明記 |
| M7 | DriftMonitorのベースラインが固定 | 月次リフレッシュに変更 |
| M8 | response.content[0].text直接アクセス | typeフィルタリングに変更 |
| M9 | 前処理のユニットテストなし | テスト仕様を追加 |
| M10 | ロギング未設計 | 監査証跡仕様を追加 |
| M11 | レバレッジ5倍が高すぎる | 実効エクスポージャー上限を追加 |
| M13 | ファンディングレートが警告のみ | 期待リターンから控除 |
| M14 | max_drawdown_pctにハードリミットなし | 絶対上限25%をハードコード |

### v3.1.1 修正一覧（Gemini・Codex敵対的レビュー対応）

#### P0（致命的修正）

| ID | 問題 | 修正内容 | レビュー元 |
|---|---|---|---|
| R-A1 | `CIRCUIT_BREAKER`がOutput Schema・ExecutionManagerで未処理 | `FORCE_CLOSE`（ポジションあり）/ `NO_TRADE`（ポジションなし）に統一 | Codex A-1 |
| R-A2 | `FORCE_CLOSE`後にreturnがなくSL/TP登録に落ちる | `place_order()`にreturn追加 | Codex A-2 |
| R-FC | `FORCE_CLOSE`失敗時の無制限成行フォールバック | 段階的スリッページ上限リトライ（0.5%→1.0%→2.0%）+ 人間エスカレーション | Gemini P0, Codex R-1 |
| R-WS | `RealtimeMonitor`の1秒RESTポーリングがレートリミット抵触 | WebSocket User Data Stream + REST 30秒ヘルスチェックのハイブリッド | Gemini P0 |

#### P1（重大修正）

| ID | 問題 | 修正内容 | レビュー元 |
|---|---|---|---|
| R-M1 | System Promptが「算術禁止」と「価格計算せよ」を同時要求 | Python側で`pre_computed_levels`を事前計算。LLMはsignal選択のみ | Codex M-1 |
| R-Q3 | `vol_threshold`を計算するが未使用。高ボラのノイズトレンド誤認 | レジーム判定に`volatility_cv > vol_threshold`条件追加。`VOLATILE`レジーム新設 | Codex Q-3 |
| R-M2 | Pydanticがビジネス制約（価格方向整合性等）を検証しない | `model_validator`でsignal別の価格方向・size・FORCE_CLOSE制約を検証 | Codex M-2 |
| R-Q1 | Kelly入力が同一分布から同時推定されておらず過大サイジング | `MAX_KELLY_FRACTION`を0.25→0.10に暫定引き下げ | Codex Q-1, Gemini #1 |
| R-M3 | DriftMonitorが劣化状態を新baselineにする | `alert_active`中はbaseline更新をスキップ | Codex M-3 |

### v3.1.2 修正一覧（残課題対応）

| ID | 問題 | 修正内容 | レビュー元 |
|---|---|---|---|
| R-SM | 注文状態管理の欠如（order ID, partial fill, cancel/replace, reduce-only） | `ManagedOrder`データモデル + `OrderState`状態機械を新設。ExecutionManagerを全面改定 | Codex A-3 |
| R-KI | Kelly入力が異なる情報源から推定され過大サイジング | regime×signal別の同時推定スクリプト（`calibrate_kelly_inputs.py`）を追加。移行手順を明記 | Codex Q-1, Gemini #1 |
| R-LF | バックテスト勝率（fallback）と本番LLM判断の乖離が未監視 | `_log_llm_fallback_divergence()`をrunnerに追加。全LLM判断でfallbackと並行比較 | Codex Q-2 |
| R-DD | ドローダウン・日次損失の定義が曖昧 | 付録Dで equity/daily_pnl/drawdown/unrealized_pnl の計算式・入出金補正・リセット時刻を明文化 | Codex R-2 |

---

## 2. Python前処理レイヤー仕様

### 2-1. 完全な前処理コード

```python
"""
kronos_preprocessor.py  (v3.1)
Kronos予測出力 → LLM入力用の事前計算済みJSON生成
全数値計算はここで完結。LLMは計算を一切行わない。

v3.1変更点:
  - [C1]  Kelly式を正規形に修正
  - [C2]  WIN_RATE_LOOKUPを連続関数化（ロジスティック回帰）
  - [C3]  ADX proxyを線形回帰R²に変更
  - [C4]  レジーム判定を複合条件に変更
  - [C5]  動的スリッページ推定
  - [C6]  勝率連動の非対称R:R
  - [M1]  Kelly期待リターンをmedianベースに変更
  - [M11] 実効エクスポージャー上限を追加
  - [M13] ファンディングレートを期待リターンから控除
  - [M14] max_drawdown_pctにハードリミット追加
"""

import numpy as np
from dataclasses import dataclass, asdict
from typing import Optional
from pydantic import BaseModel, field_validator  # [C8] 出力バリデーション用
import json
import logging
from scipy import stats  # [C3] 線形回帰用

# ============================================================
# ロギング設定 [M10]
# ============================================================
logger = logging.getLogger("kronos.preprocessor")

# ============================================================
# 定数（バックテスト結果に基づき調整すること）
# ============================================================

# [C3][C4] レジーム判定閾値（線形回帰R²ベース）
REGIME_R2_THRESHOLD = 0.40  # R² > 0.40 でトレンドと判定
REGIME_VOLATILITY_THRESHOLDS = {
    "1h":  0.8,
    "4h":  1.5,
    "1d":  3.0,
}

# シグナル閾値（レジーム別、forecast_return %）
SIGNAL_THRESHOLDS = {
    "TRENDING": 1.0,
    "RANGING":  1.5,
    "VOLATILE": 2.0,  # [v3.1.1] 高ボラ時は高い閾値を要求
}

# [C2] 信頼度スコア → 実績勝率マッピング（ロジスティック回帰パラメータ）
# キャリブレーション手順: セクション5-1参照
# win_rate = 1 / (1 + exp(-(a * confidence_score + b)))
# 初期値はバックテスト前の仮パラメータ。必ずキャリブレーションすること。
WIN_RATE_LOGISTIC_A = 0.04   # 傾き
WIN_RATE_LOGISTIC_B = -2.0   # 切片
WIN_RATE_FLOOR = 0.40        # 下限（0以下のconfidenceでも最低勝率）
WIN_RATE_CEILING = 0.65      # 上限（過信防止）

# 異常値検知のATR倍率
ANOMALY_ATR_MULTIPLIER = 5.0

# [C1][v3.1.1] Kelly計算の上限
# v3.1では0.25だったが、Kelly入力(win_prob, expected_gain, expected_loss)が
# 同一バックテスト母集団で同時推定されていないため、過大サイジングリスクを緩和。
# 同一条件下での再推定完了後に0.25まで戻すことを検討。
MAX_KELLY_FRACTION = 0.10

# [M11] 実効エクスポージャー上限（Kelly × leverage の上限）
MAX_EFFECTIVE_EXPOSURE = 1.25  # 最大125%

# ハードリミット
ABSOLUTE_MAX_DAILY_LOSS_PCT = 5.0
MAX_LEVERAGE_ALLOWED = 5.0
ABSOLUTE_MAX_DRAWDOWN_PCT = 25.0  # [M14] max_drawdown_pctの絶対上限

# [C6] R:R倍率（勝率連動）
# 勝率が高いほどR:Rを1:1に近づけ、低いほどR:Rを有利にする
def compute_rr_multipliers(win_rate: float) -> tuple[float, float]:
    """
    Returns (sl_atr_multiplier, tp1_atr_multiplier).
    勝率に応じてSL/TPの非対称性を調整。
    
    win_rate >= 0.58: SL=1.5 ATR, TP1=1.5 ATR (1:1)
    win_rate == 0.52: SL=1.2 ATR, TP1=1.8 ATR (1:1.5)
    win_rate <= 0.45: SL=1.0 ATR, TP1=2.0 ATR (1:2)
    線形補間で中間値を算出。
    """
    if win_rate >= 0.58:
        return (1.5, 1.5)
    elif win_rate <= 0.45:
        return (1.0, 2.0)
    else:
        # 0.45〜0.58 の線形補間
        t = (win_rate - 0.45) / (0.58 - 0.45)
        sl_mult = 1.0 + 0.5 * t    # 1.0 → 1.5
        tp_mult = 2.0 - 0.5 * t    # 2.0 → 1.5
        return (round(sl_mult, 3), round(tp_mult, 3))


def estimate_win_rate(confidence_score: float) -> float:
    """
    [C2] ロジスティック回帰で信頼度スコアから勝率を推定。
    初期パラメータは仮値。バックテスト後にキャリブレーションすること。
    """
    logit = WIN_RATE_LOGISTIC_A * confidence_score + WIN_RATE_LOGISTIC_B
    raw = 1.0 / (1.0 + np.exp(-logit))
    return float(np.clip(raw, WIN_RATE_FLOOR, WIN_RATE_CEILING))


def estimate_slippage(
    order_size_usd: float,
    bid_ask_spread_pct: float,
    hour_utc: int,
    recent_volume_usd: float,
) -> float:
    """
    [C5] 動的スリッページ推定。
    
    Parameters:
        order_size_usd: 注文サイズ（USD）
        bid_ask_spread_pct: 現在のbid-askスプレッド（%）
        hour_utc: 現在時刻（UTC、0-23）
        recent_volume_usd: 直近1時間の出来高（USD）
    
    Returns:
        推定スリッページ（%）
    """
    # ベース: bid-askスプレッドの半分
    base = bid_ask_spread_pct / 2.0
    
    # サイズインパクト: 出来高に対する注文比率
    if recent_volume_usd > 0:
        size_ratio = order_size_usd / recent_volume_usd
        size_impact = size_ratio * 0.5  # 出来高の1%で0.5%のインパクト
    else:
        size_impact = 0.1  # 出来高データなしは保守的
    
    # 時間帯補正: アジア深夜（UTC 20-03）は流動性低下
    if hour_utc >= 20 or hour_utc <= 3:
        time_multiplier = 1.5
    elif 13 <= hour_utc <= 20:  # NY時間帯
        time_multiplier = 0.8
    else:
        time_multiplier = 1.0
    
    estimated = (base + size_impact) * time_multiplier
    
    # 下限0.01%、上限0.5%
    return float(np.clip(estimated, 0.01, 0.50))


@dataclass
class PreprocessedInput:
    """LLMに渡す事前計算済みデータ"""
    
    # === 現在の市場状態 ===
    current_price: float
    candle_interval: str
    
    # === Kronos予測統計量 ===
    forecast_return_pct: float        # mean return（参考値）
    forecast_uncertainty_pct: float   # 平均CV
    forecast_atr: float
    path_agreement_ratio: float
    sample_count: int
    temperature: float
    top_p: float
    median_return_pct: float          # [M1] Kelly計算・方向判定に使用
    iqr_return_pct: float
    max_path_return_pct: float
    min_path_return_pct: float
    
    # === レジーム判定結果 [C3][C4] ===
    regime: str                       # TRENDING_UP / TRENDING_DOWN / RANGING
    regime_r_squared: float           # 線形回帰R²
    regime_slope_sign: int            # +1 / -1 / 0
    volatility_cv: float              # CV（ボラティリティ指標として保持）
    price_position: float
    
    # === 方向判定 ===
    direction: str                    # BULLISH / BEARISH / NEUTRAL
    signal_threshold_used: float
    
    # === 信頼度スコア ===
    confidence_score: float
    confidence_level: str
    penalties_applied: list
    bonuses_applied: list
    
    # === Kelly計算結果 [C1][C2] ===
    win_probability: float            # ロジスティック回帰推定値
    expected_gain: float              # [M1] medianベース
    expected_loss: float
    kelly_fraction: float             # half-Kelly適用済み
    base_size_usd: float
    drawdown_scalar: float
    suggested_size_usd: float
    effective_exposure_pct: float     # [M11] kelly × leverage × 100
    
    # === R:R設定 [C6] ===
    sl_atr_multiplier: float
    tp1_atr_multiplier: float
    
    # === 事前計算済み価格レベル [v3.1.1] ===
    # signal別のentry/SL/TP候補。LLMはsignalを選ぶだけで価格計算しない。
    pre_computed_levels: dict  # signal → {entry, stop_loss, take_profit_1, trailing_stop_distance}
    
    # === リス���チェック結果 ===
    circuit_breaker_active: bool
    circuit_breaker_reason: Optional[str]
    fee_check_passed: bool
    round_trip_cost_pct: float
    min_profitable_move_pct: float
    estimated_slippage_pct: float     # [C5] 動的推定値
    funding_impact: Optional[str]
    funding_cost_pct: Optional[float] # [M13] 定量値
    
    # === 入力検証結果 ===
    input_valid: bool
    validation_errors: list
    
    # === ポジション情報（パススルー）===
    current_side: str
    current_size_usd: float
    entry_price: Optional[float]
    unrealized_pnl_pct: Optional[float]
    
    # === セッション情報（パススルー）===
    daily_pnl_pct: float
    consecutive_losses: int
    current_drawdown_pct: float
    
    # === リスクパラメータ（パススルー）===
    max_position_usd: float
    leverage: float
    max_drawdown_pct: float


def preprocess(
    historical_klines: list[dict],
    kronos_forecast: dict,
    current_position: dict,
    session_state: dict,
    risk_parameters: dict,
    market_microstructure: Optional[dict] = None,  # [C5] bid-ask等
) -> PreprocessedInput:
    """全数値計算を実行し、LLM入力用の構造化データを生成"""
    
    # --- 基本データ抽出 ---
    closes = np.array([k["close"] for k in historical_klines])
    highs  = np.array([k["high"]  for k in historical_klines])
    lows   = np.array([k["low"]   for k in historical_klines])
    current_price = closes[-1]
    
    meta = kronos_forecast["meta"]
    candle_interval = meta["candle_interval"]
    paths = kronos_forecast["paths"]
    sample_count = len(paths)
    
    # [M10] ロギング
    logger.info(
        "preprocess start | price=%.2f | interval=%s | paths=%d",
        current_price, candle_interval, sample_count,
    )
    
    # ============================================================
    # GATE 0: 入力検証（異常値検知含む）
    # ============================================================
    validation_errors = []
    
    if len(historical_klines) < 50:
        validation_errors.append(
            f"historical_klines count {len(historical_klines)} < 50"
        )
    
    if sample_count < 5:
        validation_errors.append(
            f"sample_count {sample_count} < 5 (recommend >= 20)"
        )
    
    # ATRベース動的異常値閾値
    recent_atr = np.mean(highs[-20:] - lows[-20:])
    anomaly_threshold = recent_atr * ANOMALY_ATR_MULTIPLIER
    
    for i, path in enumerate(paths):
        for candle in path:
            if abs(candle["close"] - current_price) > anomaly_threshold:
                validation_errors.append(
                    f"Path {i}: forecast close {candle['close']:.2f} deviates "
                    f"> {ANOMALY_ATR_MULTIPLIER}x ATR from current "
                    f"{current_price:.2f}"
                )
                break
    
    input_valid = len(validation_errors) == 0
    
    # ============================================================
    # GATE 1: サーキットブレーカー
    # ============================================================
    cb_active = False
    cb_reason = None
    
    # [M14] max_drawdown_pct にハードリミット適用
    user_max_dd = risk_parameters.get("max_drawdown_pct", 10.0)
    max_dd = min(user_max_dd, ABSOLUTE_MAX_DRAWDOWN_PCT)
    
    effective_daily_limit = min(
        risk_parameters.get("daily_loss_limit_pct", 3.0),
        ABSOLUTE_MAX_DAILY_LOSS_PCT,
    )
    
    if session_state["daily_pnl_pct"] <= -effective_daily_limit:
        cb_active = True
        cb_reason = (
            f"Daily loss {session_state['daily_pnl_pct']:.2f}% "
            f"exceeds limit {effective_daily_limit}%"
        )
    
    max_consec = risk_parameters.get("max_consecutive_losses", 3)
    if session_state["consecutive_losses"] >= max_consec:
        cb_active = True
        cb_reason = (
            (cb_reason or "")
            + f" | Consecutive losses: {session_state['consecutive_losses']}"
        )
    
    if session_state["current_drawdown_pct"] >= max_dd:
        cb_active = True
        cb_reason = (
            (cb_reason or "")
            + f" | Drawdown {session_state['current_drawdown_pct']:.2f}% "
            f"at max ({max_dd}%)"
        )
    
    # ============================================================
    # STEP 1: Kronos予測統計量
    # ============================================================
    final_closes = np.array([path[-1]["close"] for path in paths])
    
    horizon_len = len(paths[0])
    mean_closes = []
    std_closes = []
    mean_highs_lows = []
    
    for t in range(horizon_len):
        t_closes = np.array([path[t]["close"] for path in paths])
        t_highs  = np.array([path[t]["high"]  for path in paths])
        t_lows   = np.array([path[t]["low"]   for path in paths])
        mean_closes.append(np.mean(t_closes))
        std_closes.append(
            np.std(t_closes, ddof=1) if sample_count > 1 else 0.0
        )
        mean_highs_lows.append(np.mean(t_highs - t_lows))
    
    mean_closes = np.array(mean_closes)
    std_closes = np.array(std_closes)
    
    forecast_return_mean = (
        (mean_closes[-1] - current_price) / current_price * 100
    )
    # 平均CV（ゼロ除算防止）
    safe_mean = np.where(np.abs(mean_closes) < 1e-10, 1e-10, mean_closes)
    forecast_uncertainty = float(np.mean(std_closes / safe_mean) * 100)
    forecast_atr = float(np.mean(mean_highs_lows))
    
    # パス方向一致率
    path_returns = (final_closes - current_price) / current_price
    bullish_count = np.sum(path_returns > 0)
    path_agreement = float(
        max(bullish_count, sample_count - bullish_count) / sample_count
    )
    
    # ロバスト統計量
    median_return = float(np.median(path_returns) * 100)
    q1, q3 = np.percentile(path_returns * 100, [25, 75])
    iqr_return = float(q3 - q1)
    max_path_return = float(np.max(path_returns) * 100)
    min_path_return = float(np.min(path_returns) * 100)
    
    # ============================================================
    # STEP 2: レジーム判定 [C3][C4]
    # ============================================================
    recent_closes = closes[-20:]
    x = np.arange(len(recent_closes))
    
    # 線形回帰
    slope, intercept, r_value, p_value, std_err = stats.linregress(
        x, recent_closes
    )
    r_squared = float(r_value ** 2)
    slope_sign = int(np.sign(slope))
    
    # ボラティリティ（CVとして保持、レジーム判定の補助指標）
    volatility_cv = float(
        np.std(recent_closes) / np.mean(recent_closes) * 100
    )
    vol_threshold = REGIME_VOLATILITY_THRESHOLDS.get(candle_interval, 1.5)
    
    # [v3.1.1] レジーム判定: R² + 勾配 + ボラティリティの複合条件
    # 高ボラ時はトレンド判定を抑制（ノイズトレンド誤認防止）
    if volatility_cv > vol_threshold:
        regime = "VOLATILE"  # [v3.1.1] 高ボラレジーム新設
    elif r_squared > REGIME_R2_THRESHOLD and slope_sign > 0:
        regime = "TRENDING_UP"
    elif r_squared > REGIME_R2_THRESHOLD and slope_sign < 0:
        regime = "TRENDING_DOWN"
    else:
        regime = "RANGING"
    
    price_position = float(
        (closes[-1] - np.min(lows[-20:]))
        / (np.max(highs[-20:]) - np.min(lows[-20:]) + 1e-10)
    )
    
    # ============================================================
    # STEP 3: 方向判定 [M1] medianベース
    # ============================================================
    # [v3.1.1] VOLATILEレジーム追加に対応
    if regime == "VOLATILE":
        threshold_key = "VOLATILE"
    elif regime == "RANGING":
        threshold_key = "RANGING"
    else:
        threshold_key = "TRENDING"
    signal_threshold = SIGNAL_THRESHOLDS[threshold_key]
    
    # [M1] median_return を判定に使用（外れ値耐性）
    if median_return > signal_threshold:
        direction = "BULLISH"
    elif median_return < -signal_threshold:
        direction = "BEARISH"
    else:
        direction = "NEUTRAL"
    
    # ============================================================
    # STEP 4: 信頼度スコア
    # ============================================================
    score = 100.0
    penalties = []
    bonuses = []
    
    # 不確実性ペナルティ
    if forecast_uncertainty > 2.0:
        score -= 25
        penalties.append(
            f"uncertainty {forecast_uncertainty:.2f}% > 2.0%: -25pts"
        )
    elif forecast_uncertainty > 1.0:
        score -= 10
        penalties.append(
            f"uncertainty {forecast_uncertainty:.2f}% > 1.0%: -10pts"
        )
    
    # サンプル数ペナルティ（M2強化: <20で追加ペナルティ）
    if sample_count < 5:
        score -= 30
        penalties.append(f"sample_count {sample_count} < 5: -30pts")
    elif sample_count < 10:
        score -= 15
        penalties.append(f"sample_count {sample_count} < 10: -15pts")
    elif sample_count < 20:
        score -= 5
        penalties.append(f"sample_count {sample_count} < 20: -5pts")
    
    # 温度ペナルティ
    if meta["temperature"] > 1.0:
        score -= 15
        penalties.append(
            f"temperature {meta['temperature']} > 1.0: -15pts"
        )
    
    # 予測ホライゾンペナルティ
    if horizon_len > 48:
        extra_penalty = ((horizon_len - 48) // 24 + 1) * 10
        score -= extra_penalty
        penalties.append(
            f"horizon {horizon_len} > 48 candles: -{extra_penalty}pts"
        )
    
    # [v3.1.1] VOLATILEレジームペナルティ
    if regime == "VOLATILE":
        score -= 20
        penalties.append("VOLATILE regime: -20pts (high noise)")
    
    # レジーム逆行ペナルティ
    if regime == "RANGING" and direction != "NEUTRAL":
        score -= 15
        penalties.append("signal in RANGING regime: -15pts")
    if regime == "TRENDING_UP" and direction == "BEARISH":
        score -= 20
        penalties.append(
            "BEARISH signal in TRENDING_UP: -20pts (counter-trend)"
        )
    if regime == "TRENDING_DOWN" and direction == "BULLISH":
        score -= 20
        penalties.append(
            "BULLISH signal in TRENDING_DOWN: -20pts (counter-trend)"
        )
    
    # セッションパフォーマンスペナルティ
    if session_state["daily_pnl_pct"] < -1.0:
        score -= 10
        penalties.append(
            f"session PnL {session_state['daily_pnl_pct']:.2f}%: -10pts"
        )
    
    # パス方向不一致ペナルティ
    if path_agreement < 0.6:
        score -= 20
        penalties.append(
            f"path agreement {path_agreement:.0%} < 60%: -20pts"
        )
    elif path_agreement < 0.7:
        score -= 10
        penalties.append(
            f"path agreement {path_agreement:.0%} < 70%: -10pts"
        )
    
    # mean vs median乖離ペナルティ
    mean_median_divergence = abs(forecast_return_mean - median_return)
    if mean_median_divergence > 1.0:
        score -= 15
        penalties.append(
            f"mean-median divergence {mean_median_divergence:.2f}%: "
            f"-15pts (outlier paths)"
        )
    
    # ボーナス
    if forecast_uncertainty < 0.5:
        score += 10
        bonuses.append(
            f"uncertainty {forecast_uncertainty:.2f}% < 0.5%: +10pts"
        )
    
    if (regime == "TRENDING_UP" and direction == "BULLISH") or \
       (regime == "TRENDING_DOWN" and direction == "BEARISH"):
        score += 10
        bonuses.append("regime-signal alignment: +10pts")
    
    if path_agreement > 0.85:
        score += 10
        bonuses.append(
            f"path agreement {path_agreement:.0%} > 85%: +10pts"
        )
    
    score = float(np.clip(score, 0, 100))
    
    if score >= 75:
        confidence_level = "HIGH"
    elif score >= 55:
        confidence_level = "MEDIUM"
    else:
        confidence_level = "LOW"
    
    # ============================================================
    # STEP 5: Kelly計算 [C1][C2][M1][M11][M13]
    # ============================================================
    # [C2] ロジスティック回帰で勝率推定
    win_prob = estimate_win_rate(score)
    
    # [M1] medianベースの期待リターン
    expected_gain = abs(median_return) / 100
    
    # [C6] 勝率連動のR:R倍率
    sl_atr_mult, tp1_atr_mult = compute_rr_multipliers(win_prob)
    expected_loss = (forecast_atr * sl_atr_mult) / current_price
    
    # [M13] ファンディングレートを期待リターンから控除
    funding_rate = risk_parameters.get("funding_rate_8h")
    funding_cost_pct = None
    if funding_rate is not None:
        # 保有期間のファンディングコスト推定
        # 1足 = candle_interval の時間、ファンディングは8h毎
        hours_per_candle = {"1h": 1, "4h": 4, "1d": 24}.get(
            candle_interval, 4
        )
        hold_hours = horizon_len * hours_per_candle
        funding_periods = hold_hours / 8.0
        funding_cost_pct = float(abs(funding_rate) * funding_periods)
        
        # 期待リターンからファンディングコストを控除
        if (direction == "BULLISH" and funding_rate > 0) or \
           (direction == "BEARISH" and funding_rate < 0):
            expected_gain = max(0.0, expected_gain - funding_cost_pct / 100)
    
    # [C1] 正規Kelly式: f* = (p * b - q) / b
    # b = expected_gain / expected_loss (利益/損失 比)
    if expected_gain < 1e-8 or expected_loss < 1e-8:
        kelly_f = 0.0
    else:
        b = expected_gain / expected_loss  # 利益損失比（オッズ）
        p = win_prob
        q = 1.0 - win_prob
        kelly_f = (p * b - q) / b
        # half-Kelly + 上限
        kelly_f = max(0.0, min(kelly_f * 0.5, MAX_KELLY_FRACTION))
    
    # ドローダウンスケーラー（二乗型）
    current_dd = session_state["current_drawdown_pct"]
    if max_dd > 0:
        dd_scalar = (1 - current_dd / max_dd) ** 2
    else:
        dd_scalar = 1.0
    dd_scalar = float(np.clip(dd_scalar, 0, 1))
    
    # レバレッジ制限
    effective_leverage = min(
        risk_parameters.get("leverage", 1.0),
        MAX_LEVERAGE_ALLOWED,
    )
    
    base_size = risk_parameters["max_position_usd"] * kelly_f
    suggested_size = base_size * dd_scalar
    suggested_size = min(suggested_size, risk_parameters["max_position_usd"])
    
    # [M11] 実効エクスポージャー上限チェック
    if risk_parameters["max_position_usd"] > 0:
        effective_exposure = (
            (suggested_size * effective_leverage)
            / risk_parameters["max_position_usd"]
        )
    else:
        effective_exposure = 0.0
    
    if effective_exposure > MAX_EFFECTIVE_EXPOSURE:
        suggested_size = (
            MAX_EFFECTIVE_EXPOSURE
            * risk_parameters["max_position_usd"]
            / effective_leverage
        )
        effective_exposure = MAX_EFFECTIVE_EXPOSURE
    
    # ============================================================
    # STEP 6: 手数料チェック [C5]
    # ============================================================
    taker_fee = risk_parameters.get("taker_fee_pct", 0.05)
    
    # [C5] 動的スリッページ推定
    if market_microstructure:
        est_slippage = estimate_slippage(
            order_size_usd=suggested_size,
            bid_ask_spread_pct=market_microstructure.get(
                "bid_ask_spread_pct", 0.02
            ),
            hour_utc=market_microstructure.get("hour_utc", 12),
            recent_volume_usd=market_microstructure.get(
                "recent_volume_usd", 1e8
            ),
        )
    else:
        est_slippage = 0.03  # マイクロストラクチャ未提供時の保守的デフォルト
    
    effective_fee = taker_fee + est_slippage
    round_trip_cost = 2 * effective_fee
    min_profitable_move = round_trip_cost / 100
    
    # [M1] medianベースで手数料チェック
    fee_passed = abs(median_return) / 100 > min_profitable_move
    
    # [M13] ファンディングレート影響（定量 + 警告メッセージ）
    funding_msg = None
    if funding_rate is not None:
        if direction == "BULLISH" and funding_rate > 0.01:
            funding_msg = (
                f"High funding rate {funding_rate:.4f}% "
                f"(est. cost {funding_cost_pct:.3f}% over hold period)"
            )
        elif direction == "BEARISH" and funding_rate < -0.01:
            funding_msg = (
                f"Negative funding rate {funding_rate:.4f}% "
                f"(est. cost {funding_cost_pct:.3f}% over hold period)"
            )
    
    # ============================================================
    # STEP 7: 事前計算済み価格レベル [v3.1.1]
    # LLMに算術を一切させない。全signal候補のentry/SL/TPをここで計算。
    # ============================================================
    atr = forecast_atr
    
    def _compute_levels(side: str, entry: float) -> dict:
        if side == "long":
            sl = round(entry - atr * sl_atr_mult, 2)
            tp1 = round(entry + atr * tp1_atr_mult, 2)
        else:
            sl = round(entry + atr * sl_atr_mult, 2)
            tp1 = round(entry - atr * tp1_atr_mult, 2)
        return {
            "entry": round(entry, 2),
            "stop_loss": sl,
            "take_profit_1": tp1,
            "trailing_stop_distance": round(atr * 1.0, 2),
        }
    
    limit_offset_normal = min(0.003, atr * 0.3 / current_price)
    limit_offset_weak = min(0.005, atr * 0.5 / current_price)
    
    pre_computed_levels = {
        "BUY": _compute_levels("long", current_price),
        "BUY_LIMIT": _compute_levels(
            "long", round(current_price * (1 - limit_offset_normal), 2)
        ),
        "WEAK_BUY": _compute_levels(
            "long", round(current_price * (1 - limit_offset_weak), 2)
        ),
        "SELL_SHORT": _compute_levels("short", current_price),
        "SELL_LIMIT": _compute_levels(
            "short", round(current_price * (1 + limit_offset_normal), 2)
        ),
        "WEAK_SELL": _compute_levels(
            "short", round(current_price * (1 + limit_offset_weak), 2)
        ),
    }
    
    # ============================================================
    # 組み立て
    # ============================================================
    result = PreprocessedInput(
        current_price=float(current_price),
        candle_interval=candle_interval,
        forecast_return_pct=round(float(forecast_return_mean), 4),
        forecast_uncertainty_pct=round(forecast_uncertainty, 4),
        forecast_atr=round(forecast_atr, 4),
        path_agreement_ratio=round(path_agreement, 4),
        sample_count=sample_count,
        temperature=meta["temperature"],
        top_p=meta["top_p"],
        median_return_pct=round(median_return, 4),
        iqr_return_pct=round(iqr_return, 4),
        max_path_return_pct=round(max_path_return, 4),
        min_path_return_pct=round(min_path_return, 4),
        regime=regime,
        regime_r_squared=round(r_squared, 4),
        regime_slope_sign=slope_sign,
        volatility_cv=round(volatility_cv, 4),
        price_position=round(price_position, 4),
        direction=direction,
        signal_threshold_used=signal_threshold,
        confidence_score=round(score, 2),
        confidence_level=confidence_level,
        penalties_applied=penalties,
        bonuses_applied=bonuses,
        win_probability=round(win_prob, 4),
        expected_gain=round(expected_gain, 6),
        expected_loss=round(expected_loss, 6),
        kelly_fraction=round(kelly_f, 6),
        base_size_usd=round(base_size, 2),
        drawdown_scalar=round(dd_scalar, 4),
        suggested_size_usd=round(suggested_size, 2),
        effective_exposure_pct=round(effective_exposure * 100, 2),
        sl_atr_multiplier=sl_atr_mult,
        tp1_atr_multiplier=tp1_atr_mult,
        pre_computed_levels=pre_computed_levels,
        circuit_breaker_active=cb_active,
        circuit_breaker_reason=cb_reason,
        fee_check_passed=fee_passed,
        round_trip_cost_pct=round(round_trip_cost, 4),
        min_profitable_move_pct=round(min_profitable_move * 100, 4),
        estimated_slippage_pct=round(est_slippage, 4),
        funding_impact=funding_msg,
        funding_cost_pct=round(funding_cost_pct, 4) if funding_cost_pct else None,
        input_valid=input_valid,
        validation_errors=validation_errors,
        current_side=current_position.get("side", "none"),
        current_size_usd=current_position.get("size_usd", 0.0),
        entry_price=current_position.get("entry_price"),
        unrealized_pnl_pct=current_position.get("unrealized_pnl_pct"),
        daily_pnl_pct=session_state["daily_pnl_pct"],
        consecutive_losses=session_state["consecutive_losses"],
        current_drawdown_pct=session_state["current_drawdown_pct"],
        max_position_usd=risk_parameters["max_position_usd"],
        leverage=effective_leverage,
        max_drawdown_pct=max_dd,
    )
    
    logger.info(
        "preprocess done | regime=%s | direction=%s | confidence=%s(%.1f) | "
        "kelly=%.4f | size=$%.2f",
        regime, direction, confidence_level, score,
        kelly_f, suggested_size,
    )
    
    return result


def to_llm_input(pre: PreprocessedInput) -> str:
    """LLMに渡すJSON文字列を生成"""
    return json.dumps(asdict(pre), ensure_ascii=False, indent=2)
```

### 2-2. LLM出力バリデーション [C8]

```python
"""
kronos_output_validator.py  (v3.1)
LLM出力のPydanticバリデーション。
型不整合・必須フィールド欠損を検知し、フォールバックに回す。
"""

from pydantic import BaseModel, field_validator, model_validator
from typing import Optional
import json


class TradeDecision(BaseModel):
    """LLM出力のバリデーションスキーマ"""
    signal: str
    order_type: Optional[str] = None
    entry_price_target: Optional[float] = None
    suggested_size_usd: float
    stop_loss: Optional[float] = None
    take_profit_1: Optional[float] = None
    take_profit_1_close_pct: Optional[int] = 50
    take_profit_2_mode: Optional[str] = "trailing_stop"
    trailing_stop_distance: Optional[float] = None
    max_hold_candles: Optional[int] = None
    limit_expiry_candles: Optional[int] = None
    overrides_applied: list[str] = []
    rationale: str
    warnings: list[str] = []
    risk_assessment: str
    
    @field_validator("signal")
    @classmethod
    def validate_signal(cls, v):
        allowed = {
            "BUY", "BUY_LIMIT", "SELL_SHORT", "SELL_LIMIT",
            "WEAK_BUY", "WEAK_SELL", "HOLD", "NO_TRADE", "FORCE_CLOSE",
        }
        if v not in allowed:
            raise ValueError(f"Invalid signal: {v}")
        return v
    
    @field_validator("risk_assessment")
    @classmethod
    def validate_risk(cls, v):
        if v not in {"ACCEPTABLE", "ELEVATED", "HIGH"}:
            raise ValueError(f"Invalid risk_assessment: {v}")
        return v
    
    @field_validator("suggested_size_usd")
    @classmethod
    def validate_size(cls, v):
        if v < 0:
            raise ValueError(f"suggested_size_usd must be >= 0, got {v}")
        return v
    
    @model_validator(mode="after")
    def validate_business_constraints(self):
        """[v3.1.1] signal別のビジネス制約を検証"""
        LONG_SIGNALS = {"BUY", "BUY_LIMIT", "WEAK_BUY"}
        SHORT_SIGNALS = {"SELL_SHORT", "SELL_LIMIT", "WEAK_SELL"}
        PASSIVE_SIGNALS = {"HOLD", "NO_TRADE"}
        
        # 1. エントリーシグナルには価格レベルが必須
        if self.signal in (LONG_SIGNALS | SHORT_SIGNALS):
            if self.entry_price_target is None:
                raise ValueError(
                    f"{self.signal} requires entry_price_target"
                )
            if self.stop_loss is None:
                raise ValueError(f"{self.signal} requires stop_loss")
            if self.take_profit_1 is None:
                raise ValueError(f"{self.signal} requires take_profit_1")
        
        # 2. ロング: SL < entry < TP
        if self.signal in LONG_SIGNALS and self.stop_loss and self.entry_price_target:
            if self.stop_loss >= self.entry_price_target:
                raise ValueError(
                    f"Long {self.signal}: stop_loss ({self.stop_loss}) "
                    f"must be < entry ({self.entry_price_target})"
                )
            if self.take_profit_1 and self.take_profit_1 <= self.entry_price_target:
                raise ValueError(
                    f"Long {self.signal}: take_profit_1 ({self.take_profit_1}) "
                    f"must be > entry ({self.entry_price_target})"
                )
        
        # 3. ショート: SL > entry > TP
        if self.signal in SHORT_SIGNALS and self.stop_loss and self.entry_price_target:
            if self.stop_loss <= self.entry_price_target:
                raise ValueError(
                    f"Short {self.signal}: stop_loss ({self.stop_loss}) "
                    f"must be > entry ({self.entry_price_target})"
                )
            if self.take_profit_1 and self.take_profit_1 >= self.entry_price_target:
                raise ValueError(
                    f"Short {self.signal}: take_profit_1 ({self.take_profit_1}) "
                    f"must be < entry ({self.entry_price_target})"
                )
        
        # 4. HOLD/NO_TRADE は size=0 であるべき
        if self.signal in PASSIVE_SIGNALS and self.suggested_size_usd > 0:
            raise ValueError(
                f"{self.signal} must have suggested_size_usd=0, "
                f"got {self.suggested_size_usd}"
            )
        
        # 5. FORCE_CLOSE にTP/SLが付いていてはならない
        if self.signal == "FORCE_CLOSE":
            if self.take_profit_1 is not None or self.stop_loss is not None:
                raise ValueError(
                    "FORCE_CLOSE must not have stop_loss or take_profit_1"
                )
        
        return self


def parse_llm_output(raw_text: str) -> Optional[TradeDecision]:
    """
    LLM出力をパースしてバリデーション。
    失敗時はNoneを返す（呼び出し元がフォールバックに回す）。
    """
    try:
        # JSONの前後にテキストが混入している場合に対応
        text = raw_text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        
        data = json.loads(text)
        return TradeDecision(**data)
    except Exception as e:
        logger.warning("LLM output validation failed: %s | raw: %s", e, raw_text[:200])
        return None
```

### 2-3. 呼び出しフロー

```python
"""
kronos_runner.py  (v3.1)
"""

from kronos_preprocessor import preprocess, to_llm_input
from kronos_output_validator import parse_llm_output, TradeDecision
import anthropic
import json
import time
import logging

logger = logging.getLogger("kronos.runner")

SYSTEM_PROMPT_V31 = open("system_prompt_v3.1.txt").read()

client = anthropic.Anthropic()


def run_trade_decision(
    historical_klines,
    kronos_forecast,
    current_position,
    session_state,
    risk_parameters,
    market_microstructure=None,
) -> dict:
    
    start_time = time.monotonic()
    
    # Step 1: Python前処理（決定的）
    pre = preprocess(
        historical_klines, kronos_forecast,
        current_position, session_state, risk_parameters,
        market_microstructure,
    )
    
    # Step 2: 早期離脱（LLM不要なケース）
    # [v3.1.1] CIRCUIT_BREAKERを廃止。ExecutionManagerが処理可能なシグナルに統一。
    if pre.circuit_breaker_active:
        if pre.current_side != "none":
            # 既存ポジションあり → 即座にクローズ
            result = {
                "signal": "FORCE_CLOSE",
                "order_type": "market",
                "suggested_size_usd": 0,
                "rationale": f"Circuit breaker: {pre.circuit_breaker_reason}",
                "force_close_reason": pre.circuit_breaker_reason,
                "risk_assessment": "HIGH",
                "overrides_applied": ["circuit_breaker"],
                "warnings": [],
            }
        else:
            # ポジションなし → 新規取引禁止
            result = {
                "signal": "NO_TRADE",
                "suggested_size_usd": 0,
                "rationale": f"Circuit breaker: {pre.circuit_breaker_reason}",
                "risk_assessment": "HIGH",
                "overrides_applied": ["circuit_breaker"],
                "warnings": [],
            }
        _log_decision(pre, result, start_time, llm_called=False)
        return result
    
    if not pre.input_valid:
        result = {
            "signal": "INVALID_INPUT",
            "validation_errors": pre.validation_errors,
            "suggested_size_usd": 0,
        }
        _log_decision(pre, result, start_time, llm_called=False)
        return result
    
    if not pre.fee_check_passed:
        result = {
            "signal": "NO_TRADE",
            "reason": (
                f"median_return {pre.median_return_pct:.2f}% <= "
                f"min_profitable_move {pre.min_profitable_move_pct:.4f}%"
            ),
            "suggested_size_usd": 0,
        }
        _log_decision(pre, result, start_time, llm_called=False)
        return result
    
    # Step 3: LLM判断（非決定的判断のみ委任）
    llm_input = to_llm_input(pre)
    
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            temperature=0,  # [C7] 再現性向上
            system=SYSTEM_PROMPT_V31,
            messages=[{"role": "user", "content": llm_input}],
        )
        
        # [M8] content blockをtypeでフィルタリング
        text_blocks = [
            block.text for block in response.content
            if block.type == "text"
        ]
        if not text_blocks:
            raise ValueError("No text block in LLM response")
        
        raw_text = text_blocks[0]
        
        # [C8] Pydanticバリデーション
        validated = parse_llm_output(raw_text)
        if validated is None:
            raise ValueError("LLM output failed Pydantic validation")
        
        result = validated.model_dump()
        
    except Exception as e:
        logger.error("LLM call failed, using fallback: %s", e)
        result = _fallback_rule_based(pre)
        result["_fallback"] = True
        result["_error"] = str(e)
    
    # [v3.1.2] LLM判断 vs fallback判断の一致率監視
    fallback_result = _fallback_rule_based(pre)
    _log_llm_fallback_divergence(result, fallback_result, pre)
    
    _log_decision(pre, result, start_time, llm_called=True)
    return result


def _fallback_rule_based(pre) -> dict:
    """LLM障害時のルールベースフォールバック"""
    if pre.confidence_level == "LOW" or pre.direction == "NEUTRAL":
        return {"signal": "NO_TRADE", "suggested_size_usd": 0,
                "rationale": "Fallback: low confidence or neutral",
                "risk_assessment": "HIGH", "overrides_applied": [],
                "warnings": []}
    
    signal_map = {
        ("BULLISH",  "HIGH",   "TRENDING_UP"):    "BUY",
        ("BULLISH",  "HIGH",   "TRENDING_DOWN"):   "NO_TRADE",
        ("BULLISH",  "HIGH",   "RANGING"):         "BUY_LIMIT",
        ("BEARISH",  "HIGH",   "TRENDING_DOWN"):   "SELL_SHORT",
        ("BEARISH",  "HIGH",   "TRENDING_UP"):     "NO_TRADE",
        ("BEARISH",  "HIGH",   "RANGING"):         "SELL_LIMIT",
        ("BULLISH",  "MEDIUM", "TRENDING_UP"):     "WEAK_BUY",
        ("BULLISH",  "MEDIUM", "TRENDING_DOWN"):   "NO_TRADE",
        ("BULLISH",  "MEDIUM", "RANGING"):         "WEAK_BUY",
        ("BEARISH",  "MEDIUM", "TRENDING_DOWN"):   "WEAK_SELL",
        ("BEARISH",  "MEDIUM", "TRENDING_UP"):     "NO_TRADE",
        ("BEARISH",  "MEDIUM", "RANGING"):         "WEAK_SELL",
    }
    
    key = (pre.direction, pre.confidence_level, pre.regime)
    signal = signal_map.get(key, "NO_TRADE")
    
    # Override 2a: スポットのみの場合ショート不可
    overrides = []
    if pre.leverage <= 1.0 and signal in (
        "SELL_SHORT", "SELL_LIMIT", "WEAK_SELL"
    ):
        signal = "HOLD"
        overrides.append("2a: spot-only, short blocked")
    
    # Override 2b: ピラミッディング禁止
    if pre.current_side == "long" and signal in ("BUY", "BUY_LIMIT", "WEAK_BUY"):
        signal = "HOLD"
        overrides.append("2b: no pyramiding")
    if pre.current_side == "short" and signal in (
        "SELL_SHORT", "SELL_LIMIT", "WEAK_SELL"
    ):
        signal = "HOLD"
        overrides.append("2b: no pyramiding")
    
    # Override 2d: 連敗中のMEDIUM無効化
    if pre.consecutive_losses >= 2 and pre.confidence_level == "MEDIUM":
        signal = "NO_TRADE"
        overrides.append("2d: MEDIUM blocked during losing streak")
    
    # Override 2e: パス方向不一致
    if pre.path_agreement_ratio < 0.55:
        signal = "NO_TRADE"
        overrides.append("2e: path agreement < 0.55")
    
    # SL/TP計算 [C6]
    if signal in ("BUY", "BUY_LIMIT", "WEAK_BUY"):
        entry = pre.current_price
        sl = entry - pre.forecast_atr * pre.sl_atr_multiplier
        tp1 = entry + pre.forecast_atr * pre.tp1_atr_multiplier
    elif signal in ("SELL_SHORT", "SELL_LIMIT", "WEAK_SELL"):
        entry = pre.current_price
        sl = entry + pre.forecast_atr * pre.sl_atr_multiplier
        tp1 = entry - pre.forecast_atr * pre.tp1_atr_multiplier
    else:
        entry, sl, tp1 = None, None, None
    
    size = pre.suggested_size_usd if signal not in (
        "NO_TRADE", "HOLD"
    ) else 0
    
    return {
        "signal": signal,
        "order_type": "market" if signal in ("BUY", "SELL_SHORT") else
                      "limit" if signal != "NO_TRADE" and signal != "HOLD" else None,
        "entry_price_target": entry,
        "suggested_size_usd": size,
        "stop_loss": round(sl, 2) if sl else None,
        "take_profit_1": round(tp1, 2) if tp1 else None,
        "take_profit_1_close_pct": 50 if tp1 else None,
        "take_profit_2_mode": "trailing_stop" if tp1 else None,
        "trailing_stop_distance": round(pre.forecast_atr * 1.0, 2) if tp1 else None,
        "max_hold_candles": None,  # フォールバックでは設定しない
        "limit_expiry_candles": 1 if "WEAK" in (signal or "") else None,
        "overrides_applied": overrides,
        "rationale": f"Fallback rule-based: {signal}",
        "warnings": [],
        "risk_assessment": "ELEVATED",
    }


def _log_llm_fallback_divergence(
    llm_result: dict, fallback_result: dict, pre,
):
    """
    [v3.1.2] LLM判断とfallback判断の乖離を監視。
    signalが異なる場合はログに記録し、乖離率が閾値を超えたらアラート。
    
    用途:
    - バックテスト勝率（fallbackベース）が本番LLM判断にどこまで適用可能かの検証
    - LLMがfallbackと異なる判断を下す頻度・パターンの把握
    """
    llm_signal = llm_result.get("signal", "UNKNOWN")
    fb_signal = fallback_result.get("signal", "UNKNOWN")
    
    if llm_signal != fb_signal:
        logger.info(
            "LLM_FALLBACK_DIVERGENCE | llm=%s | fallback=%s | "
            "regime=%s | conf=%.1f | direction=%s",
            llm_signal, fb_signal,
            pre.regime, pre.confidence_score, pre.direction,
        )
    
    # メトリクス収集（Prometheus/StatsD等に送信する想定）
    _emit_metric("kronos.llm_fallback.total", 1)
    if llm_signal != fb_signal:
        _emit_metric("kronos.llm_fallback.diverged", 1)
    
    # 直近100回の乖離率が40%を超えたらアラート
    # （実装はDriftMonitorと同様のローリングウィンドウ）


def _emit_metric(name: str, value: float):
    """メトリクス送信（実装はインフラ依存）"""
    pass


def _log_decision(pre, result, start_time, llm_called: bool):
    """[M10] 監査証跡ログ"""
    elapsed = time.monotonic() - start_time
    logger.info(
        "DECISION | signal=%s | size=$%.2f | price=%.2f | "
        "regime=%s | conf=%.1f | kelly=%.4f | "
        "llm=%s | fallback=%s | latency=%.3fs",
        result.get("signal"), result.get("suggested_size_usd", 0),
        pre.current_price, pre.regime, pre.confidence_score,
        pre.kelly_fraction, llm_called,
        result.get("_fallback", False), elapsed,
    )
```

---

## 3. System Prompt v3.1（本体）

```
# KRONOS TRADING DECISION ENGINE v3.1
# Architecture: Pre-computed analytics → LLM judgment → Structured output

---

# Role

You are the judgment layer of a systematic crypto trading engine for BTC/USDT.

You receive PRE-COMPUTED analytics from a deterministic Python pipeline. 
All numerical calculations (statistics, Kelly fraction, regime detection, 
risk checks) are ALREADY DONE. You do NOT perform any arithmetic.

Your responsibilities:
1. Interpret the pre-computed signals in combination
2. Make the final signal decision using the decision matrix
3. Determine entry and exit price levels using the pre-computed ATR multipliers
4. Generate a concise rationale for human review
5. Apply conservative overrides when multiple warnings coexist

Output ONLY valid JSON matching the Output Schema. No text outside JSON.

---

# Input

You receive a JSON object with all fields pre-computed. Key fields:

## Market Analytics (pre-computed, treat as ground truth)
- forecast_return_pct: mean expected return (reference only)
- median_return_pct: median expected return (primary signal — outlier-resistant)
- forecast_uncertainty_pct: average coefficient of variation across paths
- forecast_atr: average predicted true range
- path_agreement_ratio: fraction of paths agreeing on direction (0.0-1.0)
- iqr_return_pct: interquartile range of path returns
- max_path_return_pct / min_path_return_pct: best/worst case paths

## Regime (pre-computed via linear regression)
- regime: TRENDING_UP | TRENDING_DOWN | RANGING | VOLATILE [v3.1.1]
- regime_r_squared: R² of 20-bar linear regression (higher = stronger trend)
- volatility_cv: coefficient of variation (%). VOLATILE if exceeds threshold.
- price_position: 0.0 (at range low) to 1.0 (at range high)

## Signal Direction (pre-computed from median_return)
- direction: BULLISH | BEARISH | NEUTRAL

## Confidence (pre-computed)  
- confidence_score: 0-100
- confidence_level: HIGH | MEDIUM | LOW
- penalties_applied / bonuses_applied: list of scoring adjustments

## Position Sizing (pre-computed)
- win_probability: logistic regression estimate from confidence_score
- kelly_fraction: half-Kelly, capped at 0.25
- suggested_size_usd: adjusted for drawdown and exposure limits
- drawdown_scalar: quadratic reduction factor
- effective_exposure_pct: kelly × leverage (capped at 125%)

## Risk/Reward (pre-computed, win-rate adaptive) [v3.1]
- sl_atr_multiplier: stop-loss distance in ATR units (1.0–1.5)
- tp1_atr_multiplier: take-profit-1 distance in ATR units (1.5–2.0)
  Higher win_probability → symmetric (1.5/1.5)
  Lower win_probability → asymmetric (1.0/2.0) for better R:R

## Pre-computed Price Levels [v3.1.1]
- pre_computed_levels: dict of signal → {entry, stop_loss, take_profit_1, trailing_stop_distance}
  All entry/SL/TP prices are pre-calculated by Python for each signal type.
  You MUST use these values — do NOT calculate prices yourself.

## Risk Checks (pre-computed)
- circuit_breaker_active: if true, input should not reach you
- fee_check_passed: if false, input should not reach you
- funding_impact: warning string or null
- funding_cost_pct: estimated funding cost over hold period (null if N/A)
- estimated_slippage_pct: dynamic estimate based on market microstructure

## Current State
- current_side / current_size_usd / entry_price / unrealized_pnl_pct
- daily_pnl_pct / consecutive_losses / current_drawdown_pct

---

# Decision Logic

## Rule 1: Signal Decision Matrix

Use the pre-computed direction and confidence_level:

| direction | confidence_level | regime         | signal      |
|-----------|-----------------|----------------|-------------|
| BULLISH   | HIGH            | TRENDING_UP    | BUY         |
| BULLISH   | HIGH            | TRENDING_DOWN  | NO_TRADE    |
| BULLISH   | HIGH            | RANGING        | BUY_LIMIT   |
| BEARISH   | HIGH            | TRENDING_DOWN  | SELL_SHORT  |
| BEARISH   | HIGH            | TRENDING_UP    | NO_TRADE    |
| BEARISH   | HIGH            | RANGING        | SELL_LIMIT  |
| BULLISH   | MEDIUM          | TRENDING_UP    | WEAK_BUY    |
| BULLISH   | MEDIUM          | TRENDING_DOWN  | NO_TRADE    |
| BULLISH   | MEDIUM          | RANGING        | WEAK_BUY    |
| BEARISH   | MEDIUM          | TRENDING_DOWN  | WEAK_SELL   |
| BEARISH   | MEDIUM          | TRENDING_UP    | NO_TRADE    |
| BEARISH   | MEDIUM          | RANGING        | WEAK_SELL   |
| ANY       | ANY             | VOLATILE       | NO_TRADE    |
| NEUTRAL   | ANY             | ANY            | HOLD        |
| ANY       | LOW             | ANY            | NO_TRADE    |

## Rule 2: Mandatory Overrides (apply in order)

a) leverage <= 1.0 → convert SELL_SHORT / SELL_LIMIT / WEAK_SELL to HOLD
   (spot-only accounts cannot short)

b) current_side matches signal direction → HOLD
   (no pyramiding: if already long and signal is BUY, hold)

c) unrealized_pnl_pct <= -(max_drawdown_pct × 0.5) → FORCE_CLOSE
   (early exit before hard drawdown limit)
   NOTE: Execution layer handles FORCE_CLOSE with graduated IOC retries
   (0.5% → 1.0% → 2.0%). No unlimited market fallback.

d) consecutive_losses >= 2 AND confidence_level == "MEDIUM" → NO_TRADE
   (tighten entry criteria during losing streak)

e) path_agreement_ratio < 0.55 → NO_TRADE
   (model paths are essentially random — no edge)

f) HIGH confidence counter-trend signals are already blocked in the matrix.
   MEDIUM confidence counter-trend signals are also blocked.

## Rule 3: Entry & Exit Levels [v3.1.1 — ALL PRE-COMPUTED]

All price levels are pre-computed by Python in the `pre_computed_levels` field.
You MUST use these values directly. Do NOT calculate any prices.

### How to use pre_computed_levels:

The input contains `pre_computed_levels`, a dict keyed by signal name.
After you decide the signal (from Rule 1 + Rule 2), look up the levels:

```
levels = pre_computed_levels[signal]
entry_price_target = levels["entry"]
stop_loss          = levels["stop_loss"]
take_profit_1      = levels["take_profit_1"]
trailing_stop_distance = levels["trailing_stop_distance"]
```

### Order type:
- BUY / SELL_SHORT → order_type = "market"
- BUY_LIMIT / SELL_LIMIT / WEAK_BUY / WEAK_SELL → order_type = "limit"
- HOLD / NO_TRADE / FORCE_CLOSE → order_type = null

### Two-tier take-profit:
- take_profit_1_close_pct = 50  (close half at TP1)
- After TP1 hit: stop_loss moves to entry (breakeven) [M5 fix]
- take_profit_2_mode = "trailing_stop" (activated after TP1)

### Time-stop:
- max_hold_candles = number of candles in Kronos forecast horizon
  NOTE: Execution layer monitors this — see Section 6.

### WEAK signal expiry:
- limit_expiry_candles = 1
  (cancel unfilled WEAK_BUY/WEAK_SELL limit after 1 candle)

## Rule 4: Conservative Judgment (YOUR core value-add)

a) CONFLICTING SIGNALS: When penalties and bonuses coexist, 
   weigh penalties MORE heavily. Default to NO_TRADE when uncertain.

b) EDGE CASES NOT IN MATRIX: If the combination of inputs doesn't 
   cleanly fit the decision matrix, choose NO_TRADE and explain why.

c) MULTIPLE WARNINGS: If 3+ penalties are applied, downgrade the 
   signal by one level (BUY → WEAK_BUY → NO_TRADE) regardless 
   of the matrix output.

d) EXTREME ASYMMETRY: If min_path_return_pct implies a loss 
   exceeding 3× the expected gain (median_return_pct), add a 
   warning and reduce suggested_size_usd by 50%.

e) POSITION MANAGEMENT: When current_side != "none", prioritize 
   protecting existing gains. If unrealized_pnl_pct > 3%, 
   suggest tightening the trailing stop rather than adding size.

---

# Output Schema

{
  "signal": "BUY" | "BUY_LIMIT" | "SELL_SHORT" | "SELL_LIMIT" |
            "WEAK_BUY" | "WEAK_SELL" | "HOLD" | "NO_TRADE" | "FORCE_CLOSE",
  "order_type": "market" | "limit" | null,
  "entry_price_target": float | null,
  "suggested_size_usd": float,
  "stop_loss": float | null,
  "take_profit_1": float | null,
  "take_profit_1_close_pct": 50,
  "take_profit_2_mode": "trailing_stop",
  "trailing_stop_distance": float | null,
  "max_hold_candles": int | null,
  "limit_expiry_candles": int | null,
  "overrides_applied": [string],
  "rationale": string,
  "warnings": [string],
  "risk_assessment": "ACCEPTABLE" | "ELEVATED" | "HIGH"
}

## Field specifications:

- signal: The final trading action after all overrides
- overrides_applied: List which override rules (2a-2f, 4a-4e) were triggered
- rationale: Max 80 words. State: (1) the signal, (2) the primary reason, 
  (3) the key risk. Do not restate numbers already in the input.
- risk_assessment: 
  - ACCEPTABLE: confidence HIGH, no warnings, fee check passed
  - ELEVATED: confidence MEDIUM or 1-2 warnings
  - HIGH: confidence LOW or 3+ warnings or drawdown_scalar < 0.5
- warnings: Include funding_impact if present. Add any judgment-based 
  warnings from Rule 4.

---

# Behavioral Constraints

1. NEVER perform arithmetic. All numbers — including entry/SL/TP prices —
   come from the pre-computed input. Use pre_computed_levels[signal] for
   price levels. Use suggested_size_usd as provided unless Rule 4d applies.

2. NEVER output signal = "CIRCUIT_BREAKER" or "INVALID_INPUT". 
   These cases are handled before reaching you.

3. Default stance is NO_TRADE. A trade requires positive evidence, 
   not merely the absence of negative signals.

4. When in doubt, choose the more conservative option. 
   Missing a trade costs nothing. A bad trade costs capital.

5. Do not hedge or qualify the JSON output with external text.
   The rationale field is for your reasoning — use it fully.

6. Never recommend increasing position size during a losing streak 
   (consecutive_losses > 0).
```

---

## 4. エッジケーステスト仕様

### 4-A. Python前処理レイヤーのユニットテスト [M9]

```python
"""
test_preprocessor.py
Python前処理レイヤーの境界値・異常系テスト
"""

import pytest
import numpy as np
from kronos_preprocessor import preprocess, estimate_win_rate, compute_rr_multipliers

# --- ヘルパー ---
def make_klines(n=50, base_price=65000, trend=0):
    """テスト用K線データ生成"""
    klines = []
    for i in range(n):
        c = base_price + trend * i + np.random.normal(0, 50)
        klines.append({
            "open": c - 10, "high": c + 100, "low": c - 100, "close": c
        })
    return klines

def make_forecast(n_paths=20, horizon=12, base_price=65000, return_pct=2.0):
    """テスト用Kronos予測データ生成"""
    target = base_price * (1 + return_pct / 100)
    paths = []
    for _ in range(n_paths):
        path = []
        for t in range(horizon):
            frac = (t + 1) / horizon
            c = base_price + (target - base_price) * frac + np.random.normal(0, 50)
            path.append({"open": c, "high": c + 80, "low": c - 80, "close": c})
        paths.append(path)
    return {
        "meta": {"candle_interval": "1h", "temperature": 0.8, "top_p": 0.9},
        "paths": paths,
    }

DEFAULT_POSITION = {"side": "none", "size_usd": 0}
DEFAULT_SESSION = {"daily_pnl_pct": 0, "consecutive_losses": 0, "current_drawdown_pct": 0}
DEFAULT_RISK = {
    "max_position_usd": 10000, "leverage": 2.0,
    "taker_fee_pct": 0.05, "max_drawdown_pct": 10.0,
}


class TestInputValidation:
    def test_insufficient_klines(self):
        result = preprocess(
            make_klines(n=30), make_forecast(),
            DEFAULT_POSITION, DEFAULT_SESSION, DEFAULT_RISK,
        )
        assert not result.input_valid
        assert any("< 50" in e for e in result.validation_errors)
    
    def test_insufficient_paths(self):
        result = preprocess(
            make_klines(), make_forecast(n_paths=3),
            DEFAULT_POSITION, DEFAULT_SESSION, DEFAULT_RISK,
        )
        assert not result.input_valid
    
    def test_anomalous_path_detected(self):
        forecast = make_forecast(return_pct=50.0)  # 50%リターン = 異常
        result = preprocess(
            make_klines(), forecast,
            DEFAULT_POSITION, DEFAULT_SESSION, DEFAULT_RISK,
        )
        assert any("deviates" in e for e in result.validation_errors)


class TestCircuitBreaker:
    def test_daily_loss_triggers(self):
        session = {**DEFAULT_SESSION, "daily_pnl_pct": -3.5}
        risk = {**DEFAULT_RISK, "daily_loss_limit_pct": 3.0}
        result = preprocess(
            make_klines(), make_forecast(),
            DEFAULT_POSITION, session, risk,
        )
        assert result.circuit_breaker_active
    
    def test_absolute_daily_limit(self):
        """ユーザー設定が10%でもハードリミット5%が適用される"""
        session = {**DEFAULT_SESSION, "daily_pnl_pct": -5.5}
        risk = {**DEFAULT_RISK, "daily_loss_limit_pct": 10.0}
        result = preprocess(
            make_klines(), make_forecast(),
            DEFAULT_POSITION, session, risk,
        )
        assert result.circuit_breaker_active


class TestMaxDrawdownHardLimit:
    def test_m14_absolute_cap(self):
        """[M14] ユーザー設定50%でもハードリミット25%が適用"""
        risk = {**DEFAULT_RISK, "max_drawdown_pct": 50.0}
        result = preprocess(
            make_klines(), make_forecast(),
            DEFAULT_POSITION, DEFAULT_SESSION, risk,
        )
        assert result.max_drawdown_pct == 25.0


class TestKellyFormula:
    def test_c1_kelly_not_always_max(self):
        """[C1] Kelly計算が常にMAX_KELLY_FRACTIONに張り付かないこと"""
        result = preprocess(
            make_klines(), make_forecast(return_pct=0.5),
            DEFAULT_POSITION, DEFAULT_SESSION, DEFAULT_RISK,
        )
        assert result.kelly_fraction < 0.25
    
    def test_kelly_zero_for_negative_edge(self):
        """エッジがない場合Kelly=0"""
        result = preprocess(
            make_klines(), make_forecast(return_pct=0.01),
            DEFAULT_POSITION, DEFAULT_SESSION, DEFAULT_RISK,
        )
        assert result.kelly_fraction == 0.0 or result.fee_check_passed is False


class TestWinRateFunction:
    def test_c2_continuous(self):
        """[C2] 勝率が連続関数であること"""
        rates = [estimate_win_rate(s) for s in range(0, 101)]
        # 単調増加
        for i in range(1, len(rates)):
            assert rates[i] >= rates[i - 1]
    
    def test_c2_bounded(self):
        """勝率が上下限内"""
        assert estimate_win_rate(0) >= 0.40
        assert estimate_win_rate(100) <= 0.65


class TestRRMultipliers:
    def test_c6_high_winrate_symmetric(self):
        sl, tp = compute_rr_multipliers(0.60)
        assert sl == 1.5 and tp == 1.5
    
    def test_c6_low_winrate_asymmetric(self):
        sl, tp = compute_rr_multipliers(0.44)
        assert sl == 1.0 and tp == 2.0


class TestEffectiveExposure:
    def test_m11_exposure_cap(self):
        """[M11] 実効エクスポージャーが125%を超えない"""
        risk = {**DEFAULT_RISK, "leverage": 5.0}
        result = preprocess(
            make_klines(), make_forecast(return_pct=5.0),
            DEFAULT_POSITION, DEFAULT_SESSION, risk,
        )
        assert result.effective_exposure_pct <= 125.0


class TestZeroDivision:
    def test_all_closes_identical(self):
        """全closeが同一値でもクラッシュしない"""
        klines = [{"open": 65000, "high": 65000, "low": 65000, "close": 65000}
                  for _ in range(50)]
        result = preprocess(
            klines, make_forecast(),
            DEFAULT_POSITION, DEFAULT_SESSION, DEFAULT_RISK,
        )
        assert result is not None
    
    def test_highs_equal_lows(self):
        """high==lowでもクラッシュしない"""
        klines = [{"open": 65000 + i, "high": 65000 + i,
                    "low": 65000 + i, "close": 65000 + i}
                  for i in range(50)]
        result = preprocess(
            klines, make_forecast(),
            DEFAULT_POSITION, DEFAULT_SESSION, DEFAULT_RISK,
        )
        assert result is not None
```

### 4-B. LLM判断テスト（v3.0テスト1〜13を継承 + v3.1追加）

テスト1〜13はv3.0から継承（変更なし）。以下はv3.1で追加されたテスト。

### テスト14: 非対称R:Rの反映確認 [C6]

```json
{
  "direction": "BULLISH",
  "confidence_level": "MEDIUM",
  "confidence_score": 60,
  "win_probability": 0.52,
  "sl_atr_multiplier": 1.2,
  "tp1_atr_multiplier": 1.8,
  "regime": "TRENDING_UP",
  "current_side": "none",
  "consecutive_losses": 0,
  "path_agreement_ratio": 0.7,
  "current_price": 65000,
  "forecast_atr": 500
}
```
**期待:** stop_loss = 65000 - 500×1.2 = 64400, take_profit_1 = 65000 + 500×1.8 = 65900。R:R = 1:1.5。

### テスト15: TP1後のSL移動 [M5]

```json
{
  "signal": "HOLD",
  "current_side": "long",
  "entry_price": 64000,
  "unrealized_pnl_pct": 2.0,
  "take_profit_1_hit": true
}
```
**期待:** 執行レイヤーがSLを entry_price (64000) に移動済み。LLMにはこの状態が `warnings` として伝達。

### テスト16: ファンディングコスト控除 [M13]

```json
{
  "direction": "BULLISH",
  "funding_rate_8h": 0.03,
  "candle_interval": "4h",
  "horizon_len": 12,
  "median_return_pct": 1.5
}
```
**期待:** 保有期間 = 12×4h = 48h。ファンディングコスト = 0.03% × (48/8) = 0.18%。expected_gain = 1.5% - 0.18% = 1.32% に減少。

### テスト17: 実効エクスポージャー上限 [M11]

```json
{
  "kelly_fraction": 0.25,
  "leverage": 5.0,
  "max_position_usd": 10000
}
```
**期待:** 実効エクスポージャー = 0.25 × 5.0 = 125%。上限ちょうどなのでそのまま。kelly_fraction=0.25でleverage=5.0超ならsuggested_size_usdが削減される。

---

## 5. バックテスト統合ガイド

### 5-1. WIN_RATE ロジスティック回帰のキャリブレーション [C2]

```python
"""
calibrate_win_rate.py
confidence_score → 実績勝率のロジスティック回帰フィッティング

[C7] バックテストはルールベースフォールバックで実施し、
LLM非決定性の影響を排除する。
"""

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import calibration_curve
import matplotlib.pyplot as plt
from collections import defaultdict

# --- Step 1: バックテストデータ収集 ---
# ルールベースフォールバック（_fallback_rule_based）を使用
# LLMは使わない → 再現性保証 [C7]

backtest_records = []  # List of {"confidence_score": float, "won": bool}

for trade in run_backtest_with_fallback():
    backtest_records.append({
        "confidence_score": trade["confidence_score"],
        "won": trade["pnl"] > 0,
    })

# --- Step 2: ロジスティック回帰フィッティング ---
X = np.array([r["confidence_score"] for r in backtest_records]).reshape(-1, 1)
y = np.array([int(r["won"]) for r in backtest_records])

model = LogisticRegression()
model.fit(X, y)

a = float(model.coef_[0][0])
b = float(model.intercept_[0])

print(f"WIN_RATE_LOGISTIC_A = {a:.6f}")
print(f"WIN_RATE_LOGISTIC_B = {b:.6f}")

# --- Step 3: キャリブレーション検証 ---
prob_true, prob_pred = calibration_curve(y, model.predict_proba(X)[:, 1], n_bins=10)

plt.figure(figsize=(8, 6))
plt.plot(prob_pred, prob_true, "s-", label="Calibration")
plt.plot([0, 1], [0, 1], "k--", label="Perfect")
plt.xlabel("Predicted Win Rate")
plt.ylabel("Actual Win Rate")
plt.title("Win Rate Calibration Curve")
plt.legend()
plt.savefig("calibration_curve.png")
print("Saved calibration_curve.png")

# --- Step 4: ビン別検証 ---
bins = [(0, 40), (40, 55), (55, 75), (75, 100)]
for lo, hi in bins:
    mask = (X.ravel() >= lo) & (X.ravel() < hi)
    if mask.sum() == 0:
        continue
    actual = y[mask].mean()
    predicted = model.predict_proba(X[mask])[:, 1].mean()
    print(f"Score {lo}-{hi}: actual={actual:.3f}, predicted={predicted:.3f}, n={mask.sum()}")
```

### 5-1b. Kelly入力の同時推定 [v3.1.2]

v3.1.1で`MAX_KELLY_FRACTION`を0.10に暫定引き下げた理由は、Kelly入力（win_prob, expected_gain, expected_loss）が異なる情報源から��定されていたこと。以下のスクリプトで同一バックテスト母集団から同時推定し、整合性を回復する。

```python
"""
calibrate_kelly_inputs.py  (v3.1.2)
regime × signal × holding_horizon ごとにKelly入力を同一母集団から同時推定。
��定完了後、MAX_KELLY_FRACTIONを0.25に戻��こと��検討可能。
"""

import numpy as np
import json
from collections import defaultdict
from dataclasses import dataclass

@dataclass
class KellyParams:
    """同時推定されたKellyパラメータ"""
    win_rate: float
    avg_win_pct: float      # 勝ちトレード条件下の平均利益 (%)
    avg_loss_pct: float     # 負けトレード条件下の平均損失 (%)
    sample_count: int
    kelly_fraction: float   # full Kelly (half-Kelly���適用側で)
    
    @property
    def is_valid(self) -> bool:
        """統計的に十分なサンプル数があるか"""
        return self.sample_count >= 30


def estimate_kelly_params_by_group(
    backtest_trades: list[dict],
) -> dict[str, KellyParams]:
    """
    バックテスト結��からregime×signal別にKellyパラメータを同時推定。
    
    backtest_trades: list of {
        "regime": str,            # TRENDING_UP / TRENDING_DOWN / RANGING / VOLATILE
        "signal": str,            # BUY / BUY_LIMIT / WEAK_BUY / ...
        "confidence_score": float,
        "pnl_pct": float,         # 取引の実現PnL (%)
        "holding_candles": int,
    }
    
    Returns: {group_key: KellyParams}
    """
    groups = defaultdict(list)
    
    for trade in backtest_trades:
        # グループ��ー: regime × signal
        key = f"{trade['regime']}_{trade['signal']}"
        groups[key].append(trade["pnl_pct"])
    
    results = {}
    for key, pnls in groups.items():
        pnls = np.array(pnls)
        wins = pnls[pnls > 0]
        losses = pnls[pnls <= 0]
        
        n = len(pnls)
        if n < 10:
            continue
        
        win_rate = len(wins) / n
        avg_win = float(np.mean(wins)) if len(wins) > 0 else 0.0
        avg_loss = float(np.abs(np.mean(losses))) if len(losses) > 0 else 0.01
        
        # Kelly: f* = (p * b - q) / b where b = avg_win / avg_loss
        if avg_loss > 0 and avg_win > 0:
            b = avg_win / avg_loss
            kelly_f = (win_rate * b - (1 - win_rate)) / b
            kelly_f = max(0.0, kelly_f)
        else:
            kelly_f = 0.0
        
        results[key] = KellyParams(
            win_rate=round(win_rate, 4),
            avg_win_pct=round(avg_win, 4),
            avg_loss_pct=round(avg_loss, 4),
            sample_count=n,
            kelly_fraction=round(kelly_f, 6),
        )
    
    return results


def export_kelly_lookup(params: dict[str, KellyParams], path: str):
    """推定結果をJSONで出力 → preprocessorで読み込み"""
    data = {}
    for key, p in params.items():
        if not p.is_valid:
            continue
        data[key] = {
            "win_rate": p.win_rate,
            "avg_win_pct": p.avg_win_pct,
            "avg_loss_pct": p.avg_loss_pct,
            "sample_count": p.sample_count,
            "kelly_fraction": p.kelly_fraction,
        }
    
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    print(f"Kelly lookup exported: {path} ({len(data)} groups)")


# --- ��用例 ---
# trades = run_backtest_with_fallback()  # 既存バックテスト
# params = estimate_kelly_params_by_group(trades)
# export_kelly_lookup(params, "kelly_lookup.json")
#
# preprocessor側での利用:
#   kelly_lookup = json.load(open("kelly_lookup.json"))
#   key = f"{regime}_{signal}"
#   if key in kelly_lookup and kelly_lookup[key]["sample_count"] >= 30:
#       kelly_f = kelly_lookup[key]["kelly_fraction"] * 0.5  # half-Kelly
#   else:
#       kelly_f = 0.0  # 未推定グループは取引���ない
```

**移行手順:**
1. 既存バックテストを実行し、全トレードの`regime`, `signal`, `pnl_pct`を記録
2. `estimate_kelly_params_by_group()`で同時推定
3. `kelly_lookup.json`をエクスポート
4. `kronos_preprocessor.py`のKelly計算部分を、lookup参照に切り替え
5. 全グループのsample_count >= 30を確認後、`MAX_KELLY_FRACTION`を0.25に戻す

### 5-2. 閾値のキャリブレーション対象一覧

| パラメータ | 初期値 | キャリブレーション方法 |
|---|---|---|
| `REGIME_R2_THRESHOLD` | 0.40 | 過去1年のR²分布で、トレンド/レンジ区分の最適カットオフをF1スコアで決定 |
| `SIGNAL_THRESHOLDS["TRENDING"]` | 1.0% | ROC分析でTPR/FPRを最適化 |
| `SIGNAL_THRESHOLDS["RANGING"]` | 1.5% | 同上 |
| `ANOMALY_ATR_MULTIPLIER` | 5.0 | 実際の最大変動幅の99パーセンタイル |
| `MAX_KELLY_FRACTION` | 0.10（暫定） | [v3.1.2] 5-1bの同時推定完了後に0.25復帰を検討 |
| `WIN_RATE_LOGISTIC_A/B` | 0.04 / -2.0 | バックテスト実績でフィッティング（5-1参照） |
| `sl_atr_multiplier` range | 1.0–1.5 | SL hitrate が 30-40% になる倍率 |
| `tp1_atr_multiplier` range | 1.5–2.0 | TP1 hitrate が 40-50% になる倍率 |
| trailing_stop_distance (ATR倍率) | 1.0 | 利益最大化 vs 早期離脱のバランス |

### 5-3. バックテスト時の注意事項

1. **[C7] LLM非決定性の排除:** バックテストは `_fallback_rule_based()` で実施。LLM判断はバックテストに使わない。LLMの付加価値は本番のエッジケース判断にのみ期待する。
2. **ルックアヘッドバイアス排除:** Kronos予測の生成時点で、予測期間のデータが学習セットに含まれていないことを確認。
3. **スリッページシミュレーション:** 成行注文は次の足の始値で約定と仮定（現在足のcloseではない）。さらに動的スリッページ推定値を加算。
4. **ファンディングレート:** 過去のファンディングレート時系列を取得し、保有期間分のコストを控除。
5. **サンプル数:** 最低500トレード分のバックテスト（統計的有意性の確保）。
6. **ウォークフォワード:** 学習期間6ヶ月→テスト期間2ヶ月のローリングウィンドウ。
7. **パフォーマンス閾値:** シャープレシオ > 1.5、最大ドローダウン < 15% を本番移行条件とする。

---

## 6. 執行レイヤー仕様（v3.1新規 / v3.1.2大幅改定）[M4][M5][C10]

### 6-1. 概要

LLMが出力した `TradeDecision` を受け取り、実際の注文発行・管理を行う。

```
TradeDecision (from LLM or fallback)
       ↓
  ExecutionManager
       ├── place_order()         : 新規注文 → ManagedOrder作成
       ├── on_order_update()     : [v3.1.2] 約定/キャンセル通知 → 状態遷移
       ├── monitor_positions()   : SL/TP/Time-stop/期限切れ監視
       ├── handle_tp1_hit()      : TP1到達時の処理 [M5]
       └── handle_force_close()  : FORCE_CLOSE執行 [C10][v3.1.1]
```

### 6-2. 注文状態機械 [v3.1.2]

全注文は以下の状態遷移に従う。各状態は `ManagedOrder.state` で追跡する。

```
NEW ──────────────────────┐
 │                        │ (cancel / expiry)
 ▼                        ▼
PARTIALLY_FILLED ──→ CANCELLED
 │
 ▼
FILLED ──→ PROTECTED ──→ TP1_FILLED ──→ TRAILING ──→ CLOSED
 │                                                      ▲
 ├─── (SL hit) ────────────────────────────────────────┘
 ├─── (time-stop) ─────────────────────────────────────┘
 └─── (force close) ───────────────────────────────────┘
```

| 状態 | 意味 | 遷移条件 |
|---|---|---|
| `NEW` | 注文発行済み、未約定 | 約定→FILLED / 部分約定→PARTIALLY_FILLED / 期限切れ→CANCELLED |
| `PARTIALLY_FILLED` | 一部約定 | 残量約定→FILLED / キャンセル→CANCELLED（約定済み分のSL/TPは登録） |
| `FILLED` | 全量約定、SL/TP未登録 | 保護注文登録完了→PROTECTED |
| `PROTECTED` | SL/TP登録済み | TP1到達→TP1_FILLED / SL到達→CLOSED / time-stop→CLOSED |
| `TP1_FILLED` | TP1で半量決済済み、SLを建値に移動済み | トレイリング起動→TRAILING |
| `TRAILING` | トレイリングストップ稼働中 | トレイリングSL到達→CLOSED / time-stop→CLOSED |
| `CANCELLED` | 注文取消し（未約定分） | 終端状態 |
| `CLOSED` | ポジション全量決済完了 | 終端状態 |

### 6-3. 注文データモデル [v3.1.2]

```python
"""
execution_manager.py  (v3.1.2)
[v3.1.2] 注文状態機械・部分約定・重複発注防止を追加
"""

import uuid
import time
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("kronos.execution")


class OrderState(Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    PROTECTED = "PROTECTED"
    TP1_FILLED = "TP1_FILLED"
    TRAILING = "TRAILING"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


@dataclass
class ManagedOrder:
    """個別注文の状態管理"""
    # 識別子
    client_order_id: str = field(
        default_factory=lambda: f"kronos-{uuid.uuid4().hex[:12]}"
    )
    exchange_order_id: Optional[str] = None
    
    # 注文内容
    signal: str = ""
    side: str = ""                    # "buy" | "sell"
    order_type: str = ""              # "market" | "limit" | "ioc"
    requested_size_usd: float = 0.0
    limit_price: Optional[float] = None
    reduce_only: bool = False
    
    # 約定状態
    state: OrderState = OrderState.NEW
    filled_size_usd: float = 0.0
    remaining_size_usd: float = 0.0
    avg_fill_price: Optional[float] = None
    
    # 保護注文
    stop_loss_price: Optional[float] = None
    stop_loss_order_id: Optional[str] = None
    take_profit_1_price: Optional[float] = None
    take_profit_1_order_id: Optional[str] = None
    take_profit_1_close_pct: int = 50
    trailing_stop_distance: Optional[float] = None
    max_hold_candles: Optional[int] = None
    
    # メタデータ
    entry_price: Optional[float] = None
    candles_held: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    close_reason: Optional[str] = None
    
    def transition(self, new_state: OrderState):
        """状態遷移（不正遷移を検出）"""
        VALID_TRANSITIONS = {
            OrderState.NEW: {
                OrderState.PARTIALLY_FILLED,
                OrderState.FILLED,
                OrderState.CANCELLED,
            },
            OrderState.PARTIALLY_FILLED: {
                OrderState.FILLED,
                OrderState.CANCELLED,
            },
            OrderState.FILLED: {OrderState.PROTECTED, OrderState.CLOSED},
            OrderState.PROTECTED: {OrderState.TP1_FILLED, OrderState.CLOSED},
            OrderState.TP1_FILLED: {OrderState.TRAILING, OrderState.CLOSED},
            OrderState.TRAILING: {OrderState.CLOSED},
        }
        allowed = VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            logger.error(
                "Invalid state transition: %s → %s (order %s)",
                self.state.value, new_state.value, self.client_order_id,
            )
            raise InvalidStateTransitionError(
                f"{self.state.value} → {new_state.value}"
            )
        old = self.state
        self.state = new_state
        self.updated_at = time.time()
        logger.info(
            "Order %s: %s → %s",
            self.client_order_id, old.value, new_state.value,
        )
```

### 6-4. ExecutionManager [v3.1.2]

```python
class ExecutionManager:
    """注文執行・ポジション管理（状態機械ベース）[v3.1.2]"""
    
    # [v3.1.1] 段階的スリッページ上限
    FORCE_CLOSE_SLIPPAGE_TIERS = [0.5, 1.0, 2.0]  # %
    
    def __init__(self, exchange_client):
        self.exchange = exchange_client
        self.active_orders: dict[str, ManagedOrder] = {}  # client_order_id → order
    
    # ================================================================
    # 新規注文
    # ================================================================
    def place_order(self, decision: dict) -> Optional[ManagedOrder]:
        signal = decision["signal"]
        
        # 重複発注防止: 同一方向のアクティブ注文がある場合は拒否
        if self._has_active_order_for_signal(signal):
            logger.warning("Duplicate order blocked: %s", signal)
            return None
        
        if signal == "FORCE_CLOSE":
            self.handle_force_close(decision)
            return None
        
        if signal in ("HOLD", "NO_TRADE"):
            return None
        
        # ManagedOrder作成
        order = ManagedOrder(
            signal=signal,
            side="buy" if "BUY" in signal else "sell",
            requested_size_usd=decision["suggested_size_usd"],
            remaining_size_usd=decision["suggested_size_usd"],
            stop_loss_price=decision.get("stop_loss"),
            take_profit_1_price=decision.get("take_profit_1"),
            take_profit_1_close_pct=decision.get("take_profit_1_close_pct", 50),
            trailing_stop_distance=decision.get("trailing_stop_distance"),
            max_hold_candles=decision.get("max_hold_candles"),
        )
        
        if signal in ("BUY", "SELL_SHORT"):
            order.order_type = "market"
            resp = self.exchange.place_order(
                client_order_id=order.client_order_id,
                side=order.side,
                type="market",
                size_usd=order.requested_size_usd,
            )
        else:
            order.order_type = "limit"
            order.limit_price = decision["entry_price_target"]
            resp = self.exchange.place_order(
                client_order_id=order.client_order_id,
                side=order.side,
                type="limit",
                price=order.limit_price,
                size_usd=order.requested_size_usd,
                time_in_force="GTC",
            )
        
        order.exchange_order_id = resp["order_id"]
        self.active_orders[order.client_order_id] = order
        logger.info(
            "Order placed: %s | %s %s | size=$%.2f | coid=%s",
            signal, order.side, order.order_type,
            order.requested_size_usd, order.client_order_id,
        )
        return order
    
    # ================================================================
    # 約定イベント処理 [v3.1.2]
    # ================================================================
    def on_order_update(self, event: dict):
        """
        取引所からの約定/キャンセル通知を処理。
        
        event keys:
          client_order_id, status, filled_size_usd,
          cumulative_filled_usd, avg_price
        """
        coid = event["client_order_id"]
        order = self.active_orders.get(coid)
        if order is None:
            logger.warning("Unknown order update: %s", coid)
            return
        
        status = event["status"]
        
        if status == "PARTIALLY_FILLED":
            order.filled_size_usd = event["cumulative_filled_usd"]
            order.remaining_size_usd = (
                order.requested_size_usd - order.filled_size_usd
            )
            order.avg_fill_price = event["avg_price"]
            if order.state == OrderState.NEW:
                order.transition(OrderState.PARTIALLY_FILLED)
        
        elif status == "FILLED":
            order.filled_size_usd = event["cumulative_filled_usd"]
            order.remaining_size_usd = 0.0
            order.avg_fill_price = event["avg_price"]
            order.entry_price = order.avg_fill_price
            order.transition(OrderState.FILLED)
            self._register_protection_orders(order)
        
        elif status in ("CANCELLED", "EXPIRED"):
            if order.filled_size_usd > 0:
                # 部分約定あり → 約定分の保護注文を数量調整して登録
                order.remaining_size_usd = 0.0
                order.entry_price = order.avg_fill_price
                order.transition(OrderState.CANCELLED)
                self._register_protection_orders(order)
            else:
                order.transition(OrderState.CANCELLED)
                del self.active_orders[coid]
    
    def _register_protection_orders(self, order: ManagedOrder):
        """約定確認後にSL/TP/Time-stopを登録（reduce-only）"""
        protect_size = order.filled_size_usd
        
        if order.stop_loss_price:
            resp = self.exchange.place_order(
                client_order_id=f"{order.client_order_id}-sl",
                side="sell" if order.side == "buy" else "buy",
                type="stop_market",
                stop_price=order.stop_loss_price,
                size_usd=protect_size,
                reduce_only=True,
            )
            order.stop_loss_order_id = resp["order_id"]
        
        if order.take_profit_1_price:
            tp_size = protect_size * (order.take_profit_1_close_pct / 100)
            resp = self.exchange.place_order(
                client_order_id=f"{order.client_order_id}-tp1",
                side="sell" if order.side == "buy" else "buy",
                type="limit",
                price=order.take_profit_1_price,
                size_usd=tp_size,
                reduce_only=True,
            )
            order.take_profit_1_order_id = resp["order_id"]
        
        if order.state == OrderState.FILLED:
            order.transition(OrderState.PROTECTED)
    
    # ================================================================
    # TP1到達 / SL到達 / Time-stop
    # ================================================================
    def handle_tp1_hit(self, order: ManagedOrder):
        """
        [M5] TP1到達時の処理:
        1. 状態遷移 → TP1_FILLED
        2. SLをentry_price（建値）にcancel & replace
        3. トレイリングストップを起動 → TRAILING
        """
        order.transition(OrderState.TP1_FILLED)
        
        # SLを建値に移動
        if order.stop_loss_order_id:
            self.exchange.cancel_order(order.stop_loss_order_id)
            remaining_size = order.filled_size_usd * (
                1 - order.take_profit_1_close_pct / 100
            )
            resp = self.exchange.place_order(
                client_order_id=f"{order.client_order_id}-sl-be",
                side="sell" if order.side == "buy" else "buy",
                type="stop_market",
                stop_price=order.entry_price,
                size_usd=remaining_size,
                reduce_only=True,
            )
            order.stop_loss_order_id = resp["order_id"]
            order.stop_loss_price = order.entry_price
        
        if order.trailing_stop_distance:
            order.transition(OrderState.TRAILING)
    
    def handle_force_close(self, decision: dict):
        """
        [C10][v3.1.1][v3.1.2] FORCE_CLOSE執行:
        1. 全保護注文をキャンセル
        2. 段階的IOCリトライ
        3. 全段階失敗 → 人間エスカレーション（無制限成行は実行しない）
        """
        for order in list(self.active_orders.values()):
            for oid in [order.stop_loss_order_id, order.take_profit_1_order_id]:
                if oid:
                    try:
                        self.exchange.cancel_order(oid)
                    except Exception as e:
                        logger.warning("Protection cancel failed: %s", e)
        
        self.exchange.cancel_all_orders()
        
        for i, max_slip in enumerate(self.FORCE_CLOSE_SLIPPAGE_TIERS):
            try:
                self.exchange.close_all_positions(
                    order_type="ioc",
                    max_slippage_pct=max_slip,
                    reduce_only=True,
                )
                logger.info("FORCE_CLOSE succeeded at tier %d (%.1f%%)", i, max_slip)
                for order in self.active_orders.values():
                    if order.state not in (OrderState.CANCELLED, OrderState.CLOSED):
                        order.state = OrderState.CLOSED
                        order.close_reason = decision.get("rationale", "force_close")
                return
            except SlippageExceededError:
                logger.warning("FORCE_CLOSE tier %d failed (>%.1f%%)", i, max_slip)
        
        logger.critical(
            "FORCE_CLOSE FAILED: all tiers exhausted. MANUAL INTERVENTION REQUIRED."
        )
        self._send_alert(
            f"FORCE_CLOSE全段階失敗 | reason={decision.get('rationale', 'N/A')}"
        )
        self._set_manual_intervention_flag()
    
    # ================================================================
    # 定期監視 [v3.1.2]
    # ================================================================
    def monitor_positions(self):
        """
        [M4] 定期実行（毎足）:
        - 未約定指値の期限切れチェック
        - Time-stop / TP1 / SL チェック
        - candles_held インクリメント
        """
        for order in list(self.active_orders.values()):
            # 未約定指値の期限切れ
            if (order.state == OrderState.NEW
                    and order.order_type == "limit"):
                expiry = 1 if "WEAK" in order.signal else (
                    order.max_hold_candles or 999
                )
                order.candles_held += 1
                if order.candles_held >= expiry and order.filled_size_usd == 0:
                    self.exchange.cancel_order(order.exchange_order_id)
                    order.transition(OrderState.CANCELLED)
                    del self.active_orders[order.client_order_id]
                    continue
            
            # アクティブポジション
            if order.state in (
                OrderState.PROTECTED, OrderState.TP1_FILLED, OrderState.TRAILING
            ):
                order.candles_held += 1
                if (order.max_hold_candles
                        and order.candles_held >= order.max_hold_candles):
                    self._close_order(order, reason="time_stop")
                elif (order.state == OrderState.PROTECTED
                        and self._is_tp1_hit(order)):
                    self.handle_tp1_hit(order)
                elif self._is_sl_hit(order):
                    self._close_order(order, reason="stop_loss")
    
    def _close_order(self, order: ManagedOrder, reason: str):
        """ポジションクローズ共通処理"""
        for oid in [order.stop_loss_order_id, order.take_profit_1_order_id]:
            if oid:
                try:
                    self.exchange.cancel_order(oid)
                except Exception:
                    pass
        self.exchange.close_position(
            side=order.side,
            size_usd=order.filled_size_usd,
            reduce_only=True,
        )
        order.close_reason = reason
        order.transition(OrderState.CLOSED)
    
    def _has_active_order_for_signal(self, signal: str) -> bool:
        """同一方向の重複注文を検出"""
        buy_signals = {"BUY", "BUY_LIMIT", "WEAK_BUY"}
        sell_signals = {"SELL_SHORT", "SELL_LIMIT", "WEAK_SELL"}
        target_side = (
            "buy" if signal in buy_signals
            else "sell" if signal in sell_signals
            else None
        )
        if target_side is None:
            return False
        return any(
            o.side == target_side
            and o.state not in (OrderState.CANCELLED, OrderState.CLOSED)
            for o in self.active_orders.values()
        )
```

---

## 7. リアルタイム監視プロセス仕様（v3.1新規）[C9]

### 7-1. 概要

判断サイクル（1足ごと）とは**独立して常時稼働**するプロセス。判断サイクル間のギャップでサーキットブレーカーをバイパスする問題を防止。

**[v3.1.1] アーキテクチャ変更:**
- **主系統:** WebSocket User Data Stream（プッシュ通知）でポジション・残高変更をリアルタイム受信
- **副系統:** REST APIによるヘルスチェック（30秒間隔）はWebSocket接続断時のフォールバック
- **理由:** 1秒REST APIポーリングは取引所レートリミットに抵触し、最も監視が必要なボラティリティ急増時にIPバンされるリスクがあった

```python
"""
realtime_monitor.py  (v3.1.1)
[C9] 判断サイクルとは独立した常時稼働プロセス。
[v3.1.1] WebSocket User Data Streamベースに変更。
  REST APIポーリングはヘルスチェック（30秒間隔）に限定。
"""

import asyncio
import time
import logging

logger = logging.getLogger("kronos.realtime_monitor")

# WebSocket再接続のバックオフ設定
WS_RECONNECT_BASE_SEC = 1
WS_RECONNECT_MAX_SEC = 30
# RESTヘルスチェック間隔
REST_HEALTH_CHECK_INTERVAL_SEC = 30


class RealtimeMonitor:
    """
    WebSocket User Data Streamでポジション変更をリアルタイム監視。
    以下の条件を常時監視:
      1. 日次損失リミット
      2. ポジション単体の損失リミット
      3. 全体ドローダウンリミット
    条件違反時は段階的クローズを実行。
    
    定義:
      - daily_pnl_pct: UTC 00:00リセット、未実現損益込みのequityベース
      - drawdown_pct: 全期間最高equity基準、未実現損益込み
      - 入出金はequity計算から除外
    """
    
    def __init__(self, exchange_client, risk_config: dict):
        self.exchange = exchange_client
        self.daily_loss_limit = min(
            risk_config.get("daily_loss_limit_pct", 3.0),
            5.0,  # ハードリミット
        )
        self.max_drawdown = min(
            risk_config.get("max_drawdown_pct", 10.0),
            25.0,  # [M14] ハードリミット
        )
        self.position_loss_limit = risk_config.get(
            "position_loss_limit_pct", 5.0
        )
        self._ws_connected = False
        self._last_health_check = 0
        self._ws_reconnect_attempts = 0
    
    async def run_forever(self):
        """メインループ: WebSocket + RESTヘルスチェック並行実行"""
        await asyncio.gather(
            self._ws_listener(),
            self._rest_health_loop(),
        )
    
    async def _ws_listener(self):
        """WebSocket User Data Streamからプッシュ受信"""
        while True:
            try:
                async with self.exchange.user_data_stream() as ws:
                    self._ws_connected = True
                    self._ws_reconnect_attempts = 0
                    logger.info("WebSocket User Data Stream connected")
                    
                    async for event in ws:
                        if event["type"] == "ACCOUNT_UPDATE":
                            self._on_account_update(event["data"])
                        elif event["type"] == "ORDER_UPDATE":
                            self._on_order_update(event["data"])
                            
            except Exception as e:
                self._ws_connected = False
                self._ws_reconnect_attempts += 1
                backoff = min(
                    WS_RECONNECT_BASE_SEC * (2 ** self._ws_reconnect_attempts),
                    WS_RECONNECT_MAX_SEC,
                )
                logger.error(
                    "WebSocket disconnected: %s | reconnect in %ds (attempt %d)",
                    e, backoff, self._ws_reconnect_attempts,
                )
                # WebSocket断の間はRESTフォールバックが補完
                await asyncio.sleep(backoff)
    
    async def _rest_health_loop(self):
        """REST APIヘルスチェック（30秒間隔、WebSocket断時は補完監視）"""
        while True:
            try:
                account = self.exchange.get_account_snapshot()
                self._last_health_check = time.monotonic()
                
                # WebSocket断中はREST結果でリスクチェック
                if not self._ws_connected:
                    logger.warning("WebSocket down — using REST fallback")
                    self._check_risk_limits(account)
                    
            except Exception as e:
                logger.error("REST health check failed: %s", e)
                if not self._ws_connected:
                    self._send_alert(
                        "MONITORING DEGRADED: WebSocket down + REST failed. "
                        "Manual check required."
                    )
            
            await asyncio.sleep(REST_HEALTH_CHECK_INTERVAL_SEC)
    
    def _on_account_update(self, data: dict):
        """WebSocketアカウント更新イベントのハンドラ"""
        self._check_risk_limits(data)
    
    def _on_order_update(self, data: dict):
        """WebSocket注文更新イベントのハンドラ（部分約定追跡等）"""
        logger.debug("Order update: %s", data)
    
    def _check_risk_limits(self, account: dict):
        """共通リスクチェックロジック"""
        # 1. 日次損失チェック
        if account["daily_pnl_pct"] <= -self.daily_loss_limit:
            self._emergency_close_all(
                f"Daily loss {account['daily_pnl_pct']:.2f}% "
                f"breached limit {self.daily_loss_limit}%"
            )
            return
        
        # 2. 全体ドローダウンチェック
        if account["drawdown_pct"] >= self.max_drawdown:
            self._emergency_close_all(
                f"Drawdown {account['drawdown_pct']:.2f}% "
                f"breached limit {self.max_drawdown}%"
            )
            return
        
        # 3. ポジション単体チェック
        for pos in account.get("positions", []):
            if pos["unrealized_pnl_pct"] <= -self.position_loss_limit:
                self._emergency_close_position(
                    pos,
                    f"Position loss {pos['unrealized_pnl_pct']:.2f}% "
                    f"breached limit {self.position_loss_limit}%"
                )
    
    def _emergency_close_all(self, reason: str):
        """
        [v3.1.1] 段階的緊急クローズ:
        1. 未約定注文を全キャンセル
        2. reduce-only IOC（段階的スリッページ上限）
        3. 全段階失敗 → アラートエスカレーション（無制限成行は実行しない）
        """
        logger.critical("EMERGENCY CLOSE ALL: %s", reason)
        try:
            self.exchange.cancel_all_orders()
        except Exception as e:
            logger.error("cancel_all_orders failed: %s", e)
        
        for max_slip in [0.5, 1.0, 2.0]:
            try:
                self.exchange.close_all_positions(
                    order_type="ioc",
                    max_slippage_pct=max_slip,
                    reduce_only=True,
                )
                self._send_alert(f"Emergency close succeeded (slip<={max_slip}%) | {reason}")
                return
            except Exception as e:
                logger.warning("Emergency close at %.1f%% failed: %s", max_slip, e)
        
        # 全段階失敗
        self._send_alert(
            f"EMERGENCY CLOSE FAILED — MANUAL INTERVENTION REQUIRED | {reason}"
        )
    
    def _emergency_close_position(self, position, reason: str):
        logger.critical(
            "EMERGENCY CLOSE: %s | %s", position["symbol"], reason
        )
        try:
            self.exchange.close_position(
                position["symbol"],
                order_type="ioc",
                max_slippage_pct=1.0,
                reduce_only=True,
            )
        except Exception as e:
            logger.error("Position close failed: %s", e)
            self._send_alert(
                f"Position close failed: {position['symbol']} | {reason} | {e}"
            )
    
    def _send_alert(self, message: str):
        # Slack / LINE Notify / email で通知
        logger.critical("[ALERT] %s", message)
```

---

## 付録A: モデルドリフト検知（改善版）[M7]

```python
"""
drift_monitor.py  (v3.1)
[M7] ベースラインの月次リフレッシュ + CUSUM検定
"""

from collections import deque
import numpy as np
import logging

logger = logging.getLogger("kronos.drift")


class DriftMonitor:
    def __init__(self, window=100, threshold_multiplier=1.5,
                 baseline_refresh_interval=2592000):  # 30日
        self.rolling_mae = deque(maxlen=window)
        self.threshold_multiplier = threshold_multiplier
        self.baseline_mae = None
        self.baseline_timestamp = None
        self.baseline_refresh_interval = baseline_refresh_interval
        self.alert_active = False
        
        # CUSUM parameters
        self.cusum_pos = 0.0
        self.cusum_neg = 0.0
        self.cusum_threshold = 0.5
    
    def update(self, predicted_close: float, actual_close: float,
               timestamp: float = None):
        error = abs(predicted_close - actual_close) / actual_close
        self.rolling_mae.append(error)
        
        if len(self.rolling_mae) < 50:
            return
        
        current_mae = np.mean(self.rolling_mae)
        
        # [M7][v3.1.1] ベースライン設定 + 月次リフレッシュ
        # alert_active中は劣化状態を新baselineにしない
        now = timestamp or __import__("time").time()
        needs_refresh = (
            self.baseline_mae is None
            or (self.baseline_timestamp and
                now - self.baseline_timestamp > self.baseline_refresh_interval)
        )
        
        if needs_refresh and len(self.rolling_mae) == self.rolling_mae.maxlen:
            # [v3.1.1] ドリフトアラート中はbaseline更新をスキップ
            if self.alert_active:
                logger.warning(
                    "Baseline refresh skipped: drift alert active "
                    "(current_mae=%.4f, baseline=%.4f)",
                    current_mae, self.baseline_mae,
                )
            else:
                old_baseline = self.baseline_mae
                self.baseline_mae = current_mae
                self.baseline_timestamp = now
                if old_baseline:
                    logger.info(
                        "Baseline refreshed: %.4f → %.4f",
                        old_baseline, current_mae,
                    )
        
        if self.baseline_mae is None:
            return
        
        # 移動平均ベースのドリフト判定
        ma_drift = current_mae > self.baseline_mae * self.threshold_multiplier
        
        # CUSUM検定（変化点検出）
        deviation = error - self.baseline_mae
        self.cusum_pos = max(0, self.cusum_pos + deviation)
        self.cusum_neg = min(0, self.cusum_neg + deviation)
        cusum_drift = self.cusum_pos > self.cusum_threshold
        
        if (ma_drift or cusum_drift) and not self.alert_active:
            self.alert_active = True
            self._send_alert(
                f"Model drift detected: MAE {current_mae:.4f} "
                f"vs baseline {self.baseline_mae:.4f} "
                f"(+{(current_mae/self.baseline_mae - 1)*100:.1f}%) "
                f"| CUSUM={self.cusum_pos:.4f}"
            )
        elif not ma_drift and not cusum_drift:
            if self.alert_active:
                logger.info("Drift alert cleared")
            self.alert_active = False
            self.cusum_pos = 0.0
            self.cusum_neg = 0.0
    
    def _send_alert(self, message: str):
        logger.critical("[DRIFT ALERT] %s", message)
    
    def get_position_scalar(self) -> float:
        if not self.alert_active:
            return 1.0
        return 0.5
```

---

## 付録B: トークン数比較

| 項目 | v2 | v3.0 | v3.1 |
|---|---|---|---|
| システムプロンプト | 約3,200 | 約2,100 | 約2,400（+R:R・執行仕様追記分） |
| ユーザー入力 | 約4,000 | 約800 | 約900（新フィールド追加分） |
| LLM出力 | 約600 | 約400 | 約400 |
| **合計** | **約7,800** | **約3,300** | **約3,700（v2比-53%）** |

---

## 付録C: 監査証跡仕様 [M10]

### ログフォーマット

全判断は以下の情報を構造化ログとして記録する：

| フィールド | 説明 |
|---|---|
| `timestamp` | UTC ISO 8601 |
| `decision_id` | UUID v4 |
| `current_price` | 判断時の価格 |
| `regime` | TRENDING_UP / TRENDING_DOWN / RANGING |
| `direction` | BULLISH / BEARISH / NEUTRAL |
| `confidence_score` | 0-100 |
| `confidence_level` | HIGH / MEDIUM / LOW |
| `kelly_fraction` | 計算結果 |
| `signal` | 最終シグナル |
| `suggested_size_usd` | 推奨サイズ |
| `llm_called` | true/false |
| `fallback_used` | true/false |
| `llm_model_version` | 使用モデル名 |
| `latency_ms` | 判断にかかった時間 |
| `preprocessed_input` | 完全なPreprocessedInput JSON |
| `llm_raw_output` | LLM生出力（デバッグ用） |
| `validated_output` | バリデーション後の出力 |

### 保持期間

- 直近3ヶ月: 全フィールド保持
- 3ヶ月〜1年: `preprocessed_input` と `llm_raw_output` を圧縮保存
- 1年超: サマリー（signal, size, pnl）のみ保持

---

## 付録D: リスク指標の定義仕様 [v3.1.2]

Codexレビュー R-2 で指摘された、ドローダウン・日次損失の定義曖昧性を解消する。

### D-1. 基準資産（Equity）の定義

```
equity = wallet_balance + unrealized_pnl - pending_fees
```

| 要素 | 定義 |
|---|---|
| `wallet_balance` | 取引所ウォレット残高（USDT建て）。入出金を含む。 |
| `unrealized_pnl` | 全オープンポジションの未実現損益。mark priceベース。 |
| `pending_fees` | 未決済のファンディング手数料。 |

**入出金補正:** equityの増減計算時、入出金イベントは除外する。具体的にはequity変動率の計算に使う基準値（`base_equity`）を入出金発生時にアジャストする。

```python
# 入出金イベント発生時
base_equity += deposit_amount  # 入金
base_equity -= withdrawal_amount  # 出金
# これにより入出金が損益として誤カウントされない
```

### D-2. daily_pnl_pct（日次損益率）

```
daily_pnl_pct = (current_equity - day_start_equity) / day_start_equity × 100
```

| パラメータ | 定義 |
|---|---|
| リセット時刻 | **UTC 00:00:00** |
| `day_start_equity` | UTC 00:00時点の equity スナップショット |
| 未実現損益 | **含む**��mark priceベース） |
| 入出金補正 | 日中の入出金は `day_start_equity` にアジャスト |

**サーキットブレーカーとの関係:**
- `daily_pnl_pct <= -daily_loss_limit` で発火
- `daily_loss_limit` = min(ユーザー設定, 5.0%)（ハードリミット）

### D-3. current_drawdown_pct（ドローダウン率）

```
high_water_mark = max(all historical equity values, adjusted for deposits/withdrawals)
current_drawdown_pct = (high_water_mark - current_equity) / high_water_mark × 100
```

| パラメータ | 定義 |
|---|---|
| 基準 | **全期間最高equity**（High Water Mark） |
| `high_water_mark` | 入出金補正済みのequity最高値。単調増加（新高値でのみ更新）。 |
| 未実現損益 | **含む** |
| リセット | なし（全期間累積） |

**サーキットブレーカーとの関係:**
- `current_drawdown_pct >= max_drawdown_pct` で発火
- `max_drawdown_pct` = min(ユーザー設定, 25.0%)（ハードリミット [M14]）

### D-4. unrealized_pnl_pct（ポジション単体の損益率）

```
unrealized_pnl_pct = (mark_price - entry_price) / entry_price × 100 × direction_sign
```

| パラメータ | 定義 |
|---|---|
| `mark_price` | 取引所のmark price（funding計算基準と同一） |
| `entry_price` | 加重平均約定価格（`ManagedOrder.avg_fill_price`） |
| `direction_sign` | long = +1, short = -1 |

**FORCE_CLOSEトリガー:**
- Rule 2c: `unrealized_pnl_pct <= -(max_drawdown_pct × 0.5)` でFORCE_CLOSE
- RealtimeMonitor: `unrealized_pnl_pct <= -position_loss_limit` で緊急クローズ

### D-5. 複数ポジション時の集計

現行設計はBTC/USDTの単一ペアだが、将来の拡張に備え集計ルールを明文化：

| 指標 | 集計方法 |
|---|---|
| `daily_pnl_pct` | 全ポジションの未実現＋実現PnLの合計を基準equityで除算 |
| `current_drawdown_pct` | equity全体（全ポジション合算）でのHWMベース |
| `unrealized_pnl_pct` | ポジション個別に計算（集計しない） |

### D-6. session_state の供給元

```python
def compute_session_state(exchange_client) -> dict:
    """
    RealtimeMonitorおよびpreprocessorに供給するsession_state。
    全指標はここで統一的に計算する。
    """
    account = exchange_client.get_account_snapshot()
    
    return {
        "daily_pnl_pct": _compute_daily_pnl(account),          # D-2
        "current_drawdown_pct": _compute_drawdown(account),     # D-3
        "consecutive_losses": _count_consecutive_losses(account),
    }
```

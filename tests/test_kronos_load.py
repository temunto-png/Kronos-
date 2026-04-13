"""
Kronos-small モデルのロード・推論スモークテスト
サンプルCSVデータを使用してモデルが正常動作することを確認する
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "kronos_model"))

import pandas as pd
import torch

print("=" * 60)
print("Kronos-small ロード・推論テスト")
print("=" * 60)

# 1. 環境確認
print(f"\n[1/4] 環境確認")
print(f"  PyTorch: {torch.__version__}")
print(f"  CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"  GPU: {torch.cuda.get_device_name(0)}")
    print(f"  VRAM: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")

# 2. モデルロード
print(f"\n[2/4] モデル・トークナイザーロード (NeoQuasar/Kronos-small)")
from model import Kronos, KronosTokenizer, KronosPredictor

tokenizer = KronosTokenizer.from_pretrained("NeoQuasar/Kronos-Tokenizer-base")
model = Kronos.from_pretrained("NeoQuasar/Kronos-small")
predictor = KronosPredictor(model, tokenizer, max_context=512)
print("  ロード完了")

# モデルサイズ確認
param_count = sum(p.numel() for p in model.parameters())
print(f"  パラメータ数: {param_count / 1e6:.1f}M")

# 3. テストデータ準備（サンプルCSVを使用）
print(f"\n[3/4] テストデータ準備")
csv_path = os.path.join(os.path.dirname(__file__), "..", "kronos_model", "examples", "data", "XSHG_5min_600977.csv")
df = pd.read_csv(csv_path)
df["timestamps"] = pd.to_datetime(df["timestamps"])

lookback = 400
pred_len = 30  # 推論時間短縮のため120→30

x_df = df.loc[:lookback - 1, ["open", "high", "low", "close", "volume", "amount"]]
x_timestamp = df.loc[:lookback - 1, "timestamps"]
y_timestamp = df.loc[lookback:lookback + pred_len - 1, "timestamps"]

print(f"  入力ローソク足数: {len(x_df)}")
print(f"  予測ステップ数: {pred_len}")
print(f"  close 範囲: {x_df['close'].min():.2f} - {x_df['close'].max():.2f}")

# 4. 推論実行
print(f"\n[4/4] 推論実行")
pred_df = predictor.predict(
    df=x_df,
    x_timestamp=x_timestamp,
    y_timestamp=y_timestamp,
    pred_len=pred_len,
    T=1.0,
    top_p=0.9,
    sample_count=1,
    verbose=True,
)

print("\n予測結果 (先頭5行):")
print(pred_df.head())
print(f"\n予測close 範囲: {pred_df['close'].min():.2f} - {pred_df['close'].max():.2f}")
print("\n[OK] テスト完了 -- Kronos-small 正常動作確認")

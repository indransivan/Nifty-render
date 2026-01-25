import os
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
from breeze_connect import BreezeConnect

# =========================
# LOAD ENV VARIABLES
# =========================
API_KEY = os.environ.get("BREEZE_API_KEY")
API_SECRET = os.environ.get("BREEZE_API_SECRET")
SESSION_TOKEN = os.environ.get("BREEZE_SESSION_TOKEN")

# =========================
# LOGIN
# =========================
breeze = BreezeConnect(api_key=API_KEY)
breeze.generate_session(api_secret=API_SECRET, session_token=SESSION_TOKEN)

print("✅ Breeze login successful")

# =========================
# FETCH DATA
# =========================
end_date = datetime.now()
start_date = end_date - timedelta(days=10)
fmt = "%Y-%m-%d %H:%M:%S"

hist_data = breeze.get_historical_data_v2(
    interval="5minute",
    from_date=start_date.strftime(fmt),
    to_date=end_date.strftime(fmt),
    stock_code="NIFTY",
    exchange_code="NSE",
    product_type="cash"
)

df = pd.DataFrame(hist_data["Success"])
df["datetime"] = pd.to_datetime(df["datetime"])

for col in ["open", "high", "low", "close", "volume"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# =========================
# RESAMPLE TO 15 MIN
# =========================
df_15 = (
    df.set_index("datetime")
    .resample("15T")
    .agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    })
    .dropna()
    .reset_index()
)

df_15["index"] = range(len(df_15))

# =========================
# MACD LOGIC
# =========================
exp1 = df_15["close"].ewm(span=12).mean()
exp2 = df_15["close"].ewm(span=26).mean()
macd = exp1 - exp2
signal = macd.ewm(span=9).mean()

buy_signal = (macd > 0) & (macd.shift(1) <= 0)
sell_signal = (macd < 0) & (macd.shift(1) >= 0)

# =========================
# SAVE CHART (HTML)
# =========================
fig = go.Figure()

fig.add_trace(go.Candlestick(
    x=df_15["datetime"],
    open=df_15["open"],
    high=df_15["high"],
    low=df_15["low"],
    close=df_15["close"],
    name="NIFTY 15m"
))

fig.add_trace(go.Scatter(
    x=df_15.loc[buy_signal, "datetime"],
    y=df_15.loc[buy_signal, "low"] * 0.998,
    mode="markers",
    marker=dict(symbol="triangle-up", size=14, color="green"),
    name="BUY"
))

fig.add_trace(go.Scatter(
    x=df_15.loc[sell_signal, "datetime"],
    y=df_15.loc[sell_signal, "high"] * 1.002,
    mode="markers",
    marker=dict(symbol="triangle-down", size=14, color="red"),
    name="SELL"
))

fig.update_layout(title="NIFTY 15m MACD Signals", template="plotly_white")

fig.write_html("nifty_macd.html")

print("📊 Chart saved as nifty_macd.html")

# =========================
# CONSOLE ALERT
# =========================
if buy_signal.iloc[-1]:
    print("🟢 BUY SIGNAL DETECTED")
elif sell_signal.iloc[-1]:
    print("🔴 SELL SIGNAL DETECTED")
else:
    print("⚪ NO SIGNAL")

print("✅ Script execution completed")

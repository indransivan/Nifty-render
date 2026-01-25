import os
from flask import Flask, jsonify
import pandas as pd
from datetime import datetime, timedelta
import plotly.graph_objects as go
from breeze_connect import BreezeConnect

app = Flask(__name__)

# ==========================================================
# ENV VARIABLES (SET IN RENDER DASHBOARD)
# ==========================================================
API_KEY = os.environ.get("BREEZE_API_KEY")
API_SECRET = os.environ.get("BREEZE_API_SECRET")
SESSION_TOKEN = os.environ.get("BREEZE_SESSION_TOKEN")

# ==========================================================
# LOGIN (ONCE)
# ==========================================================
breeze = BreezeConnect(api_key=API_KEY)
breeze.generate_session(api_secret=API_SECRET, session_token=SESSION_TOKEN)

print("✅ Breeze login successful")

# ==========================================================
# FETCH + CLEAN DATA
# ==========================================================
def get_nifty_15min():
    end = datetime.utcnow()
    start = end - timedelta(days=10)
    fmt = "%Y-%m-%d %H:%M:%S"

    hist = breeze.get_historical_data_v2(
        interval="5minute",
        from_date=start.strftime(fmt),
        to_date=end.strftime(fmt),
        stock_code="NIFTY",
        exchange_code="NSE",
        product_type="cash"
    )

    df = pd.DataFrame(hist["Success"])
    df["datetime"] = pd.to_datetime(df["datetime"])

    # ---------- TIMEZONE SAFE CONVERSION ----------
    if df["datetime"].dt.tz is None:
        df["datetime"] = df["datetime"].dt.tz_localize("Asia/Kolkata")
    else:
        df["datetime"] = df["datetime"].dt.tz_convert("Asia/Kolkata")

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # ---------- FILTER NSE MARKET HOURS ----------
    df = df[
        (df["datetime"].dt.time >= pd.to_datetime("09:15").time()) &
        (df["datetime"].dt.time <= pd.to_datetime("15:30").time())
    ]

    # ---------- RESAMPLE TO 15 MIN ----------
    df15 = (
        df.set_index("datetime")
        .resample("15min")
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

    return df15

# ==========================================================
# MACD LOGIC
# ==========================================================
def macd_signals(df):
    exp1 = df["close"].ewm(span=12).mean()
    exp2 = df["close"].ewm(span=26).mean()

    macd = exp1 - exp2
    signal = macd.ewm(span=9).mean()

    buy = (macd > 0) & (macd.shift(1) <= 0)
    sell = (macd < 0) & (macd.shift(1) >= 0)

    return macd, signal, buy, sell

# ==========================================================
# ROUTES
# ==========================================================
@app.route("/")
def chart():
    df = get_nifty_15min()
    macd, signal, buy, sell = macd_signals(df)

    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=df["datetime"],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name="NIFTY 15m"
    ))

    fig.add_trace(go.Scatter(
        x=df.loc[buy, "datetime"],
        y=df.loc[buy, "low"] * 0.998,
        mode="markers",
        marker=dict(symbol="triangle-up", size=14, color="green"),
        name="BUY"
    ))

    fig.add_trace(go.Scatter(
        x=df.loc[sell, "datetime"],
        y=df.loc[sell, "high"] * 1.002,
        mode="markers",
        marker=dict(symbol="triangle-down", size=14, color="red"),
        name="SELL"
    ))

    fig.update_layout(
        title="NIFTY 15min MACD (09:15–15:30 IST)",
        template="plotly_white",
        xaxis=dict(
            type="date",
            tickformat="%H:%M",
            dtick=15 * 60 * 1000,
            rangeslider=dict(visible=False)
        ),
        height=600
    )

    return fig.to_html(full_html=True)

@app.route("/signal")
def signal_api():
    df = get_nifty_15min()
    macd, signal, buy, sell = macd_signals(df)

    latest = {
        "time": df["datetime"].iloc[-1].strftime("%Y-%m-%d %H:%M"),
        "close": round(df["close"].iloc[-1], 2),
        "macd": round(macd.iloc[-1], 2),
        "signal": round(signal.iloc[-1], 2),
        "trend": "BULLISH" if macd.iloc[-1] > signal.iloc[-1] else "BEARISH",
        "buy": bool(buy.iloc[-1]),
        "sell": bool(sell.iloc[-1])
    }

    return jsonify(latest)

@app.route("/health")
def health():
    return {"status": "OK", "time": datetime.now().isoformat()}

# ==========================================================
# ENTRY POINT (RENDER)
# ==========================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

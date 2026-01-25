import os
from flask import Flask, jsonify
import pandas as pd
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from breeze_connect import BreezeConnect

app = Flask(__name__)

# ==========================================================
# ENV VARIABLES (SET IN RENDER)
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
# DATA FETCH + CLEAN
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

    # Timezone-safe (Render = UTC)
    if df["datetime"].dt.tz is None:
        df["datetime"] = df["datetime"].dt.tz_localize("Asia/Kolkata")
    else:
        df["datetime"] = df["datetime"].dt.tz_convert("Asia/Kolkata")

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # NSE market hours only
    df = df[
        (df["datetime"].dt.time >= pd.to_datetime("09:15").time()) &
        (df["datetime"].dt.time <= pd.to_datetime("15:30").time())
    ]

    # Resample to 15 min
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

    # 🔥 Compressed session index (NO GAPS)
    df15["x"] = range(len(df15))

    return df15

# ==========================================================
# MACD LOGIC
# ==========================================================
def macd_signals(df):
    exp1 = df["close"].ewm(span=12).mean()
    exp2 = df["close"].ewm(span=26).mean()

    macd = exp1 - exp2
    signal = macd.ewm(span=9).mean()
    hist = macd - signal

    buy = (macd > 0) & (macd.shift(1) <= 0)
    sell = (macd < 0) & (macd.shift(1) >= 0)

    return macd, signal, hist, buy, sell

# ==========================================================
# ROUTES
# ==========================================================
@app.route("/")
def chart():
    df = get_nifty_15min()
    macd, signal, hist, buy, sell = macd_signals(df)

    # ---------- SUBPLOTS (PRICE + MACD) ----------
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.7, 0.3],
        subplot_titles=[
            "NIFTY 15min Price (Gap-Free)",
            "MACD (12,26,9)"
        ]
    )

    # ---------- PRICE CANDLES ----------
    fig.add_trace(
        go.Candlestick(
            x=df["x"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="NIFTY 15m",
            hovertext=df["datetime"].dt.strftime("%Y-%m-%d %H:%M"),
            hoverinfo="text"
        ),
        row=1, col=1
    )

    # BUY markers
    fig.add_trace(
        go.Scatter(
            x=df.loc[buy, "x"],
            y=df.loc[buy, "low"] * 0.998,
            mode="markers",
            marker=dict(symbol="triangle-up", size=14, color="green"),
            name="BUY"
        ),
        row=1, col=1
    )

    # SELL markers
    fig.add_trace(
        go.Scatter(
            x=df.loc[sell, "x"],
            y=df.loc[sell, "high"] * 1.002,
            mode="markers",
            marker=dict(symbol="triangle-down", size=14, color="red"),
            name="SELL"
        ),
        row=1, col=1
    )

    # ---------- MACD HISTOGRAM ----------
    fig.add_trace(
        go.Bar(
            x=df["x"],
            y=hist,
            name="Histogram",
            marker_color=["green" if h >= 0 else "red" for h in hist],
            opacity=0.6
        ),
        row=2, col=1
    )

    # MACD line
    fig.add_trace(
        go.Scatter(
            x=df["x"],
            y=macd,
            line=dict(color="blue", width=2),
            name="MACD"
        ),
        row=2, col=1
    )

    # Signal line
    fig.add_trace(
        go.Scatter(
            x=df["x"],
            y=signal,
            line=dict(color="orange", width=2),
            name="Signal"
        ),
        row=2, col=1
    )

    # ---------- X-AXIS LABELS (TIME, NO GAPS) ----------
    step = max(len(df) // 10, 1)
    fig.update_xaxes(
        tickmode="array",
        tickvals=df["x"][::step],
        ticktext=df["datetime"].dt.strftime("%d %b %H:%M")[::step],
        row=2, col=1
    )

    fig.update_layout(
        height=800,
        template="plotly_white",
        showlegend=True,
        title="NIFTY 15min MACD Strategy (Gap-Free Session Chart)"
    )

    return fig.to_html(full_html=True)

@app.route("/signal")
def signal_api():
    df = get_nifty_15min()
    macd, signal, hist, buy, sell = macd_signals(df)

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

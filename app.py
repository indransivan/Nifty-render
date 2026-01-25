import os
from flask import Flask, jsonify, render_template_string
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

    # Compressed session index (NO GAPS)
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
# CURRENT SIGNAL STATUS
# ==========================================================
def get_current_signal():
    df = get_nifty_15min()
    macd, signal, hist, buy, sell = macd_signals(df)
    
    latest_close = df["close"].iloc[-1]
    latest_macd = macd.iloc[-1]
    latest_signal = signal.iloc[-1]
    
    if latest_macd > latest_signal:
        trend = "🟢 BULLISH"
        alert_class = "bullish"
    else:
        trend = "🔴 BEARISH"
        alert_class = "bearish"
    
    latest_signal = {
        "time": df["datetime"].iloc[-1].strftime("%H:%M:%S"),
        "price": round(latest_close, 2),
        "macd": round(latest_macd, 4),
        "signal_line": round(latest_signal, 4),
        "trend": trend,
        "buy_signal": bool(buy.iloc[-1]),
        "sell_signal": bool(sell.iloc[-1])
    }
    
    return latest_signal, alert_class

# ==========================================================
# CHART 1: NIFTY 15MIN WITH PROMINENT ALERTS
# ==========================================================
@app.route("/nifty")
def nifty_chart():
    df = get_nifty_15min()
    macd, signal_line, hist, buy, sell = macd_signals(df)
    
    current_signal, alert_class = get_current_signal()

    fig = go.Figure()

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
        )
    )

    # ---------- PROMINENT BUY ALERTS ----------
    if buy.any():
        fig.add_trace(
            go.Scatter(
                x=df.loc[buy, "x"],
                y=df.loc[buy, "low"] * 0.995,
                mode="markers+text",
                marker=dict(symbol="triangle-up", size=20, color="limegreen", line=dict(width=3, color="darkgreen")),
                name="🚀 BUY ALERT",
                text=["🚀 BUY<br>₹" + str(round(p, 2)) for p in df.loc[buy, "close"]],
                textposition="middle center",
                textfont=dict(size=14, color="white", family="Arial Black"),
                hovertemplate="🟢 BUY SIGNAL<br>Price: ₹%{text}<br>Time: %{customdata}<extra></extra>",
                customdata=df.loc[buy, "datetime"].dt.strftime("%H:%M")
            )
        )

    # ---------- PROMINENT SELL ALERTS ----------
    if sell.any():
        fig.add_trace(
            go.Scatter(
                x=df.loc[sell, "x"],
                y=df.loc[sell, "high"] * 1.005,
                mode="markers+text",
                marker=dict(symbol="triangle-down", size=20, color="crimson", line=dict(width=3, color="darkred")),
                name="💥 SELL ALERT",
                text=["💥 SELL<br>₹" + str(round(p, 2)) for p in df.loc[sell, "close"]],
                textposition="middle center",
                textfont=dict(size=14, color="white", family="Arial Black"),
                hovertemplate="🔴 SELL SIGNAL<br>Price: ₹%{text}<br>Time: %{customdata}<extra></extra>",
                customdata=df.loc[sell, "datetime"].dt.strftime("%H:%M")
            )
        )

    # ---------- VOLUME ----------
    fig.add_trace(
        go.Bar(
            x=df["x"],
            y=df["volume"],
            name="Volume",
            yaxis="y2",
            marker_color="rgba(158,202,225,0.6)",
            opacity=0.4
        )
    )

    # ---------- LAYOUT ----------
    step = max(len(df) // 10, 1)
    fig.update_xaxes(
        tickmode="array",
        tickvals=df["x"][::step],
        ticktext=df["datetime"].dt.strftime("%d %b %H:%M")[::step],
        title="Session Time (Gap-Free)"
    )

    fig.update_layout(
        height=700,
        template="plotly_white",
        title=f"📈 NIFTY 15min | Current: {current_signal['trend']} | Last: {current_signal['time']}",
        yaxis_title="Price (₹)",
        yaxis2=dict(title="Volume", side="right", overlaying="y", showgrid=False),
        showlegend=True,
        hovermode="x unified"
    )

    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    
    # HTML with alerts + auto-refresh
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>NIFTY 15min Alerts</title>
        <meta http-equiv="refresh" content="300"> <!-- 5 minutes -->
        <style>
            body {{ font-family: 'Segoe UI', Arial; margin: 0; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }}
            .container {{ max-width: 1400px; margin: 0 auto; background: white; border-radius: 15px; box-shadow: 0 20px 40px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%); padding: 20px; text-align: center; color: white; }}
            .alert-banner {{
                padding: 15px; text-align: center; font-size: 24px; font-weight: bold; 
                margin: 0 20px 20px 20px; border-radius: 10px; box-shadow: 0 5px 15px rgba(0,0,0,0.2);
            }}
            .bullish {{ background: linear-gradient(90deg, #00b09b, #96c93d); color: white; animation: pulse 2s infinite; }}
            .bearish {{ background: linear-gradient(90deg, #ff6b6b, #ee5a24); color: white; animation: shake 0.5s infinite; }}
            @keyframes pulse {{ 0% {{ transform: scale(1); }} 50% {{ transform: scale(1.02); }} 100% {{ transform: scale(1); }} }}
            @keyframes shake {{ 0%, 100% {{ transform: translateX(0); }} 25% {{ transform: translateX(-5px); }} 75% {{ transform: translateX(5px); }} }}
            .chart-container {{ padding: 20px; }}
            .status {{ padding: 15px; background: #f8f9fa; border-left: 5px solid #007bff; margin-bottom: 20px; }}
            .refresh-info {{ text-align: center; color: #666; font-style: italic; padding: 10px; background: #e9ecef; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🚀 NIFTY 15min Trading Dashboard</h1>
                <p>Auto-refresh every 5 minutes | Last update: {datetime.now().strftime('%H:%M:%S IST')}</p>
            </div>
            
            <div class="alert-banner {alert_class}">
                {current_signal['trend']} | Price: ₹{current_signal['price']} | MACD: {current_signal['macd']} 
                {'🟢 BUY NOW!' if current_signal['buy_signal'] else ''}{'🔴 SELL NOW!' if current_signal['sell_signal'] else ''}
            </div>
            
            <div class="chart-container">
                <div id="chart">{chart_html}</div>
            </div>
            
            <div class="refresh-info">
                🔄 Auto-refreshing every 5 minutes... Next refresh: {datetime.now().strftime('%H:%M:%S')} + 5min
            </div>
        </div>
    </body>
    </html>
    """.format(chart_html=chart_html, **current_signal, alert_class=alert_class)
    
    return html_template

# ==========================================================
# CHART 2: MACD WITH ALERTS (unchanged structure, enhanced alerts)
# ==========================================================
@app.route("/macd")
def macd_chart():
    df = get_nifty_15min()
    macd_line, signal_line, hist, buy, sell = macd_signals(df)
    current_signal, alert_class = get_current_signal()

    fig = go.Figure()
    
    # MACD Line, Signal Line, Histogram (same as before but with bigger markers)
    fig.add_trace(go.Scatter(x=df["x"], y=macd_line, line=dict(color="blue", width=3), name="MACD"))
    fig.add_trace(go.Scatter(x=df["x"], y=signal_line, line=dict(color="orange", width=3), name="Signal"))
    fig.add_trace(go.Bar(x=df["x"], y=hist, name="Histogram", marker_color=["green" if h >= 0 else "red" for h in hist], opacity=0.7))
    fig.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.7)

    # Enhanced crossover alerts
    if buy.any():
        fig.add_trace(go.Scatter(
            x=df.loc[buy, "x"], y=df.loc[buy, macd_line] * 1.2,
            mode="markers+text", marker=dict(symbol="triangle-up", size=18, color="lime"),
            name="🟢 BUY CROSS", text=["BUY↑"]*len(df.loc[buy]), textposition="bottom center",
            textfont=dict(size=12, color="darkgreen")
        ))
    
    if sell.any():
        fig.add_trace(go.Scatter(
            x=df.loc[sell, "x"], y=df.loc[sell, macd_line] * 0.8,
            mode="markers+text", marker=dict(symbol="triangle-down", size=18, color="red"),
            name="🔴 SELL CROSS", text=["SELL↓"]*len(df.loc[sell]), textposition="top center",
            textfont=dict(size=12, color="darkred")
        ))

    step = max(len(df) // 10, 1)
    fig.update_xaxes(tickmode="array", tickvals=df["x"][::step], ticktext=df["datetime"].dt.strftime("%d %b %H:%M")[::step])
    fig.update_layout(height=600, title=f"🎛️ MACD Alerts | {current_signal['trend']}", template="plotly_white", hovermode="x unified")

    chart_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
    
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>MACD Alerts</title>
        <meta http-equiv="refresh" content="300">
        <style>
            body {{ font-family: 'Segoe UI', Arial; margin: 0; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); }}
            .container {{ max-width: 1400px; margin: 0 auto; background: white; border-radius: 15px; box-shadow: 0 20px 40px rgba(0,0,0,0.1); overflow: hidden; }}
            .header {{ background: linear-gradient(90deg, #4facfe 0%, #00f2fe 100%); padding: 20px; text-align: center; color: white; }}
            .alert-banner.{alert_class} {{ padding: 15px; text-align: center; font-size: 20px; font-weight: bold; margin: 20px; border-radius: 10px; box-shadow: 0 5px 15px rgba(0,0,0,0.2); animation: pulse 2s infinite; }}
            .chart-container {{ padding: 20px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎛️ MACD (12,26,9) Analysis</h1>
                <p>Auto-refresh every 5 minutes</p>
            </div>
            <div class="alert-banner {alert_class}">
                {current_signal['trend']} | Price: ₹{current_signal['price']}
            </div>
            <div class="chart-container">
                <div id="chart">{chart_html}</div>
            </div>
        </div>
    </body>
    </html>
    """.format(chart_html=chart_html, **current_signal, alert_class=alert_class)
    
    return html_template

# ==========================================================
# DASHBOARD with prominent alerts
# ==========================================================
@app.route("/")
def dashboard():
    current_signal, alert_class = get_current_signal()
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>NIFTY MACD Dashboard</title>
        <meta http-equiv="refresh" content="300">
        <style>
            body {{ font-family: 'Segoe UI', sans-serif; margin: 0; padding: 20px; background: #f0f2f5; }}
            .header {{ text-align: center; padding: 30px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border-radius: 15px; margin-bottom: 20px; }}
            .alert-banner {{ padding: 20px; text-align: center; font-size: 28px; font-weight: bold; margin: 20px; border-radius: 15px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); }}
            .bullish {{ background: linear-gradient(90deg, #00b09b, #96c93d); color: white; animation: pulse 2s infinite; }}
            .bearish {{ background: linear-gradient(90deg, #ff6b6b, #ee5a24); color: white; animation: shake 0.5s infinite; }}
            .nav {{ text-align: center; margin: 30px 0; }}
            .nav a {{ display: inline-block; padding: 15px 30px; margin: 0 15px; background: #007bff; color: white; text-decoration: none; border-radius: 10px; font-weight: bold; font-size: 16px; }}
            .nav a:hover {{ background: #0056b3; transform: translateY(-2px); }}
            @keyframes pulse {{ 0% {{ transform: scale(1); }} 50% {{ transform: scale(1.03); }} 100% {{ transform: scale(1); }} }}
            @keyframes shake {{ 0%, 100% {{ transform: translateX(0); }} 25% {{ transform: translateX(-5px); }} 75% {{ transform: translateX(5px); }} }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>📊 NIFTY 15min MACD Strategy Dashboard</h1>
            <p><strong>Auto-refresh every 5 minutes</strong> | Current Time: {datetime.now().strftime('%H:%M:%S IST')}</p>
        </div>
        
        <div class="alert-banner {alert_class}">
            {current_signal['trend']} | NIFTY: ₹{current_signal['price']} | MACD: {current_signal['macd']}
            {' 🟢 LIVE BUY SIGNAL!' if current_signal['buy_signal'] else ''}{' 🔴 LIVE SELL SIGNAL!' if current_signal['sell_signal'] else ''}
        </div>
        
        <div class="nav">
            <a href="/nifty" target="_blank">📈 Price Chart + Alerts</a>
            <a href="/macd" target="_blank">🎛️ MACD Chart + Alerts</a>
            <a href="/signal">📡 JSON API</a>
        </div>
        
        <iframe src="/nifty" width="100%" height="800" frameborder="0" style="border-radius: 10px; display: block; margin: 20px 0;"></iframe>
    </body>
    </html>
    """.format(**current_signal, alert_class=alert_class)

# ==========================================================
# API ROUTES
# ==========================================================
@app.route("/signal")
def signal_api():
    signal, _ = get_current_signal()
    return jsonify(signal)

@app.route("/health")
def health():
    return {"status": "OK", "time": datetime.now().isoformat()}

# ==========================================================
# ENTRY POINT
# ==========================================================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

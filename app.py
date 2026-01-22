from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import pytz
from datetime import datetime
import traceback

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_nifty_data_safe():
    """100% crash-proof Nifty data fetcher"""
    try:
        print("📡 Fetching Nifty data...")
        
        # Simple data fetch
        ticker = yf.Ticker("^NSEI")
        hist = ticker.history(period="5d", interval="5m")
        
        if hist.empty:
            print("❌ No data returned")
            return None
            
        print(f"✅ Got {len(hist)} bars")
        
        # Safe timezone handling
        hist = hist.tz_localize('Asia/Kolkata') if hist.index.tz is None else hist
        
        # Filter market hours (simple)
        hist = hist.between_time("09:00", "16:00")
        
        if len(hist) < 20:  # Need minimum data for MACD
            print("❌ Insufficient data")
            return None
        
        # Current price (safe)
        current_price = float(hist['Close'].iloc[-1])
        timestamp = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%H:%M:%S')
        
        # MACD calculation (safe)
        closes = hist['Close'].dropna().tail(100).values  # Last 100 bars max
        macd_line = pd.Series(closes).ewm(span=12).mean() - pd.Series(closes).ewm(span=26).mean()
        signal_line = macd_line.ewm(span=9).mean()
        histogram = macd_line - signal_line
        
        # Simple signals
        buy_signals = []
        sell_signals = []
        for i in range(1, min(50, len(macd_line))):
            if macd_line.iloc[i] > 0 and macd_line.iloc[i-1] <= 0:
                buy_signals.append(i)
            if macd_line.iloc[i] < 0 and macd_line.iloc[i-1] >= 0:
                sell_signals.append(i)
        
        return {
            "success": True,
            "price": current_price,
            "time": timestamp,
            "closes": closes[-50:].tolist(),  # Last 50 bars
            "macd": macd_line[-50:].tolist(),
            "signal": signal_line[-50:].tolist(),
            "histogram": histogram[-50:].tolist(),
            "buy_signals": buy_signals[-10:],  # Last 10
            "sell_signals": sell_signals[-10:],
            "status": "BULLISH" if macd_line.iloc[-1] > 0 else "BEARISH"
        }
        
    except Exception as e:
        print(f"❌ FULL ERROR: {traceback.format_exc()}")
        return None

@app.get("/")
async def home():
    return HTMLResponse("""
<!DOCTYPE html>
<html>
<head>
    <title>Nifty Live MACD 📈</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
    <style>
        body { 
            margin: 0; padding: 20px; 
            background: #0a0a0f; 
            color: white; 
            font-family: -apple-system, sans-serif;
            min-height: 100vh;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        .header { 
            text-align: center; 
            background: linear-gradient(45deg, #1e3a8a, #3b82f6); 
            padding: 30px; 
            border-radius: 20px; 
            margin-bottom: 30px;
        }
        .price { 
            font-size: 3em; 
            color: #ffd700; 
            text-shadow: 0 0 30px #ffd700;
            margin: 10px 0;
        }
        #chart { width: 100%; height: 70vh; border-radius: 15px; }
        button { 
            background: #ef4444; 
            color: white; 
            border: none; 
            padding: 15px 30px; 
            border-radius: 50px; 
            font-size: 18px; 
            cursor: pointer; 
            margin: 10px;
        }
        button:hover { background: #dc2626; transform: scale(1.05); }
        .status { 
            text-align: center; 
            font-size: 1.5em; 
            margin: 20px 0; 
            padding: 20px; 
            border-radius: 15px; 
            background: rgba(255,255,255,0.1);
        }
        .bullish { border: 3px solid #10b981; background: rgba(16,185,129,0.2); }
        .bearish { border: 3px solid #ef4444; background: rgba(239,68,68,0.2); }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>📈 Nifty 50 Live + MACD Dashboard</h1>
            <div class="price" id="price">Loading...</div>
            <div id="time"></div>
        </div>
        
        <div class="status" id="status">Loading...</div>
        
        <div id="chart"></div>
        
        <div style="text-align: center; margin: 30px 0;">
            <button onclick="loadData()">🔄 Refresh Now</button>
            <button id="autoBtn" onclick="toggleAuto()">▶ Auto Update: OFF</button>
        </div>
    </div>

    <script>
        let autoInterval = null;
        
        async function loadData() {
            try {
                const res = await fetch('/api/nifty');
                const data = await res.json();
                
                if (!data.success) {
                    document.getElementById('status').innerHTML = '❌ No market data';
                    return;
                }
                
                // Update UI
                document.getElementById('price').textContent = `₹${data.price.toFixed(2)}`;
                document.getElementById('time').textContent = data.time;
                
                const statusEl = document.getElementById('status');
                statusEl.textContent = `MACD: ${data.macd[data.macd.length-1].toFixed(3)} | ${data.status}`;
                statusEl.className = `status ${data.status.toLowerCase()}`;
                
                // Chart
                const x = Array(data.closes.length).fill().map((_, i) => i);
                
                const traces = [
                    {
                        x: x, y: data.closes, 
                        type: 'scatter', mode: 'lines',
                        name: 'Nifty Price', line: {color: '#3b82f6', width: 3}
                    },
                    {
                        x: x, y: Array(x.length).fill(data.price),
                        type: 'scatter', mode: 'lines',
                        name: 'Live Price', line: {color: '#ef4444', width: 2, dash: 'dash'}
                    },
                    {
                        x: x, y: data.macd,
                        type: 'scatter', mode: 'lines',
                        name: 'MACD', line: {color: '#10b981', width: 2}, yaxis: 'y2'
                    },
                    {
                        x: x, y: data.signal,
                        type: 'scatter', mode: 'lines',
                        name: 'Signal', line: {color: '#f59e0b', width: 2}, yaxis: 'y2'
                    },
                    {
                        x: x, y: data.histogram,
                        type: 'bar', name: 'Histogram',
                        marker: {color: '#6b7280'}, opacity: 0.4, yaxis: 'y2'
                    }
                ];
                
                // Buy/Sell signals
                if (data.buy_signals.length > 0) {
                    traces.push({
                        x: data.buy_signals, y: data.buy_signals.map((_, i) => data.macd[data.buy_signals[i]] || 0),
                        mode: 'markers', name: 'BUY ▲',
                        marker: {size: 12, color: '#10b981', symbol: 'triangle-up'}, yaxis: 'y2'
                    });
                }
                
                Plotly.newPlot('chart', traces, {
                    height: window.innerHeight * 0.6,
                    grid: {rows: 2, cols: 1, rowHeights: [0.6, 0.4]},
                    template: 'plotly_dark',
                    yaxis: {title: 'Price ₹'},
                    yaxis2: {title: 'MACD', overlaying: 'y', side: 'right'},
                    margin: {t: 30}
                });
                
            } catch (e) {
                console.error(e);
                document.getElementById('status').innerHTML = 'Error: ' + e.message;
            }
        }
        
        function toggleAuto() {
            const btn = document.getElementById('autoBtn');
            if (autoInterval) {
                clearInterval(autoInterval);
                btn.textContent = '▶ Auto Update: OFF';
                autoInterval = null;
            } else {
                autoInterval = setInterval(loadData, 15000);
                btn.textContent = '⏸ Auto Update: ON';
            }
        }
        
        // Start
        loadData();
        setTimeout(toggleAuto, 3000);
    </script>
</body>
</html>
    """)

@app.get("/api/nifty")
def api_nifty():
    data = get_nifty_data_safe()
    if data is None:
        return JSONResponse({"success": False, "error": "No data"}, status_code=500)
    return data

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

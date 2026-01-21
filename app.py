from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf
import pandas as pd
import pytz
from datetime import datetime, time
from zoneinfo import ZoneInfo

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# Market hours IST
MARKET_OPEN = time(9, 15)   # 9:15 AM IST
MARKET_CLOSE = time(15, 30) # 3:30 PM IST

def is_market_open():
    """Check if within Nifty market hours (Mon-Fri, 9:15-15:30 IST)"""
    now = datetime.now(pytz.timezone('Asia/Kolkata'))
    
    # Weekdays only (Mon=0, Fri=4)
    if now.weekday() > 4:  # Saturday=5, Sunday=6
        return False
    
    current_time = now.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE

@app.get("/")
async def home():
    if not is_market_open():
        return HTMLResponse("""
        <div style="text-align:center; padding:100px; background:#1a1a2e; color:white; min-height:100vh; font-family:Arial;">
            <h1>⏰ Market Closed</h1>
            <p style="font-size:24px; color:#ffd700;">
                Nifty trading: <strong>9:15 AM - 3:30 PM IST</strong><br>
                Monday to Friday only
            </p>
            <p>App auto-restarts at 9:15 AM tomorrow!</p>
            <div style="font-size:14px; opacity:0.7; margin-top:50px;">
                Next open: 9:15 AM IST
            </div>
        </div>
        """)
    
    # Market open - show dashboard
    return HTMLResponse("""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Nifty Live 9-4 📈</title>
        <meta name="viewport" content="width=device-width">
        <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
        <style>
            body {margin:0;padding:20px;background:#0f0f23;color:white;font-family:system-ui,sans-serif;}
            .container {max-width:1000px;margin:0 auto;}
            .header {text-align:center;padding:30px;background:linear-gradient(90deg,#1e3a8a,#3b82f6);border-radius:20px;}
            .price {font-size:clamp(28px,8vw,48px);color:#ffd700;text-shadow:0 0 30px gold;}
            #chart {width:100%;height:60vh;border-radius:15px;}
            button {background:#10b981;border:none;padding:15px 30px;border-radius:50px;color:white;font-size:18px;cursor:pointer;}
            .market-status {text-align:center;padding:20px;background:rgba(16,185,129,0.2);border-radius:15px;margin:20px 0;}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📈 Nifty Live (9:15-15:30)</h1>
                <div class="price" id="price">Loading...</div>
                <div id="status"></div>
            </div>
            
            <div class="market-status">
                ✅ <strong>MARKET OPEN</strong> - Auto closes 15:30 IST
            </div>
            
            <div id="chart"></div>
            <div style="text-align:center;margin:30px 0;">
                <button onclick="checkNifty()">🔄 Live Update</button>
                <button onclick="toggleAuto()">▶ Auto: OFF</button>
            </div>
        </div>

        <script>
            let autoTimer = null;
            
            async function checkNifty() {
                try {
                    const res = await fetch('/api/nifty');
                    const data = await res.json();
                    
                    document.getElementById('price').textContent = `₹${data.price.toFixed(0)}`;
                    document.getElementById('status').textContent = 
                        `MACD: ${data.macd.toFixed(3)} | ${data.status}`;
                    
                    // Chart
                    const n = data.closes.length;
                    const x = Array(n).fill().map((_,i)=>i);
                    Plotly.newPlot('chart', [
                        {x,y:data.closes,type:'scatter',mode:'lines',name:'Price',line:{color:'#3b82f6'}},
                        {x,y:data.macd_line,type:'scatter',mode:'lines',name:'MACD',line:{color:'#10b981'}},
                        {x,y:data.signal_line,type:'scatter',mode:'lines',name:'Signal',line:{color:'#f59e0b'}}
                    ], {template:'plotly_dark',height:window.innerHeight*0.55});
                    
                    if (data.alert) {
                        alert(`🚨 ${data.alert}`);
                    }
                } catch(e) {
                    console.error(e);
                }
            }
            
            function toggleAuto() {
                if (autoTimer) {
                    clearInterval(autoTimer);
                    autoTimer = null;
                    event.target.textContent = '▶ Auto: OFF';
                } else {
                    autoTimer = setInterval(checkNifty, 30000); // 30 sec
                    event.target.textContent = '⏸ Auto: ON';
                }
            }
            
            checkNifty();
        </script>
    </body>
    </html>
    """)

@app.get("/api/nifty")
def api_nifty():
    if not is_market_open():
        return JSONResponse({
            "success": False, 
            "message": "Market closed. Active 9:15 AM - 3:30 PM IST (Mon-Fri)",
            "market_status": "CLOSED"
        })
    
    # Market open - get data
    try:
        ticker = yf.Ticker("^NSEI")
        hist = ticker.history(period="1d", interval="5m")
        
        if hist.empty:
            return JSONResponse({"success": False, "message": "No data available"})
        
        closes = hist['Close'].tail(50)
        ema12 = closes.ewm(span=12).mean()
        ema26 = closes.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        
        current_macd = macd.iloc[-1]
        prev_macd = macd.iloc[-2] if len(macd) > 1 else 0
        
        alert = None
        if current_macd > 0 and prev_macd <= 0:
            alert = "🟢 BUY - MACD Bullish Cross"
        elif current_macd < 0 and prev_macd >= 0:
            alert = "🔴 SELL - MACD Bearish Cross"
            
        return {
            "success": True,
            "price": float(closes.iloc[-1]),
            "macd": float(current_macd),
            "signal": float(signal.iloc[-1]),
            "status": "BULLISH" if current_macd > 0 else "BEARISH",
            "alert": alert,
            "closes": closes.tail(30).tolist(),
            "macd_line": macd.tail(30).tolist(),
            "signal_line": signal.tail(30).tolist(),
            "market_open": True
        }
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

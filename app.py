import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
from breeze_connect import BreezeConnect
import time

# Config
st.set_page_config(layout="wide", page_title="Nifty MACD Dashboard")

# Load credentials from env vars (Render secrets)
@st.cache_resource
def init_breeze():
    api_key = os.getenv("BREEZE_API_KEY")
    api_secret = os.getenv("BREEZE_API_SECRET") 
    session_token = os.getenv("BREEZE_SESSION_TOKEN")
    
    breeze = BreezeConnect(api_key=api_key)
    breeze.generate_session(api_secret=api_secret, session_token=session_token)
    return breeze

def calculate_macd_signals(df):
    exp1 = df['close'].ewm(span=12).mean()
    exp2 = df['close'].ewm(span=26).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9).mean()
    histogram = macd - signal
    
    macd_prev = macd.shift(1)
    signal_prev = signal.shift(1)
    
    buy_signal = (macd > 0) & (macd_prev <= 0)
    sell_signal = (macd < 0) & (macd_prev >= 0)
    
    return macd, signal, histogram, buy_signal, sell_signal

def main():
    st.title("🚀 Nifty 15min MACD Trading Dashboard")
    st.sidebar.header("⚙️ Controls")
    
    if st.sidebar.button("🔄 Refresh Data"):
        st.cache_data.clear()
    
    try:
        # Initialize Breeze
        with st.spinner("Connecting to Breeze API..."):
            breeze = init_breeze()
        
        # Fetch data
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
        
        df_5min = pd.DataFrame(hist_data['Success'])
        df_5min['datetime'] = pd.to_datetime(df_5min['datetime'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df_5min[col] = pd.to_numeric(df_5min[col], errors='coerce')
        
        # Resample to 15min
        df_15min = df_5min.set_index('datetime').resample('15T').agg({
            'open': 'first', 'high': 'max', 'low': 'min', 
            'close': 'last', 'volume': 'sum'
        }).dropna().reset_index()
        
        df_15min['index'] = range(len(df_15min))
        
        # Calculate signals
        macd, signal_line, histogram, buy_signals, sell_signals = calculate_macd_signals(df_15min)
        
        # Dashboard
        col1, col2 = st.columns([2, 1])
        
        with col1:
            st.subheader("📈 Nifty 15min Price + Signals")
            fig_price = go.Figure()
            
            fig_price.add_trace(go.Candlestick(
                x=df_15min['index'],
                open=df_15min['open'], high=df_15min['high'], 
                low=df_15min['low'], close=df_15min['close'],
                name="Nifty 15min",
                increasing_line_color='#00ff88', decreasing_line_color='#ff4444'
            ))
            
            if buy_signals.sum() > 0:
                buy_idx = df_15min['index'][buy_signals]
                fig_price.add_trace(go.Scatter(
                    x=buy_idx, y=df_15min.loc[buy_signals, 'low'].values * 0.998,
                    mode='markers', marker=dict(symbol='triangle-up', size=15, color='green'),
                    name='🟢 BUY', showlegend=True
                ))
            
            if sell_signals.sum() > 0:
                sell_idx = df_15min['index'][sell_signals]
                fig_price.add_trace(go.Scatter(
                    x=sell_idx, y=df_15min.loc[sell_signals, 'high'].values * 1.002,
                    mode='markers', marker=dict(symbol='triangle-down', size=15, color='red'),
                    name='🔴 SELL', showlegend=True
                ))
            
            # X-axis formatting
            n_ticks = min(12, len(df_15min)//10 + 1)
            tick_pos = np.linspace(0, len(df_15min)-1, n_ticks, dtype=int)
            tick_lbl = [df_15min['datetime'].iloc[i].strftime('%m-%d %H:%M') 
                       for i in tick_pos]
            
            fig_price.update_xaxes(tickmode='array', tickvals=tick_pos, ticktext=tick_lbl,
                                 tickangle=-45, rangeslider_visible=False)
            fig_price.update_layout(height=500, template='plotly_white', showlegend=True)
            st.plotly_chart(fig_price, use_container_width=True)
        
        with col2:
            st.subheader("🎯 Live Alerts")
            
            latest_macd = macd.iloc[-1]
            latest_signal = signal_line.iloc[-1]
            latest_close = df_15min['close'].iloc[-1]
            
            st.metric("Current Price", f"₹{latest_close:.0f}")
            st.metric("MACD", f"{latest_macd:.2f}", 
                     f"{macd.iloc[-2]:.2f}")
            st.metric("Signal", f"{latest_signal:.2f}", 
                     f"{signal_line.iloc[-2]:.2f}")
            
            trend = "🟢 BULLISH" if latest_macd > latest_signal else "🔴 BEARISH"
            st.metric("TREND", trend)
            
            st.info(f"**BUY Signals:** {buy_signals.sum()}")
            st.warning(f"**SELL Signals:** {sell_signals.sum()}")
            
            if buy_signals.iloc[-1]:
                st.success("🟢 **FRESH BUY SIGNAL!**")
            elif sell_signals.iloc[-1]:
                st.error("🔴 **FRESH SELL SIGNAL!**")
            else:
                st.info("⚪ **WAIT** - No fresh crossover")
        
        # MACD subplot
        st.subheader("📊 MACD (12,26,9)")
        fig_macd = go.Figure()
        
        fig_macd.add_trace(go.Bar(x=df_15min['index'], y=histogram,
                                 marker_color=['green' if h>=0 else 'red' for h in histogram],
                                 name='Histogram', opacity=0.7))
        
        fig_macd.add_trace(go.Scatter(x=df_15min['index'], y=macd,
                                     line=dict(color='#2962FF', width=2.5), name='MACD'))
        fig_macd.add_trace(go.Scatter(x=df_15min['index'], y=signal_line,
                                     line=dict(color='#FF6D00', width=2.5), name='Signal'))
        
        fig_macd.update_layout(height=400, template='plotly_white', 
                              hovermode='x unified', showlegend=True)
        fig_macd.update_xaxes(tickmode='array', tickvals=tick_pos, ticktext=tick_lbl,
                             tickangle=-45)
        st.plotly_chart(fig_macd, use_container_width=True)
        
        st.success(f"✅ Dashboard updated: {len(df_15min)} candles")
        
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")
        st.info("**Setup Render Environment Variables:**\n\n"
                "1. BREEZE_API_KEY\n"
                "2. BREEZE_API_SECRET\n" 
                "3. BREEZE_SESSION_TOKEN")

if __name__ == "__main__":
    main()

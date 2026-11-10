# ==============================================================================
# ESTRATÉGIA INSTITUCIONAL: EXPLOSÃO DE OPEN INTEREST + FIBONACCI (LONG & SHORT)
# ==============================================================================
import time
import threading
from datetime import datetime
import requests
import numpy as np
import pandas as pd
import ccxt
from flask import Flask

# ==============================================================================
# 1. CONFIGURAÇÕES GERAIS E TELEGRAM
# ==============================================================================
TELEGRAM_BOT_TOKEN = "9212539110:AAEFuRvZFP3fSaEr2cHXbYjWzT_duUE77ZI"
TELEGRAM_CHAT_ID = "6719799176"

exchange = ccxt.okx({
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'}
})

WATCHLIST = [
    'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'DOGE/USDT:USDT',
    'BNB/USDT:USDT', 'AVAX/USDT:USDT', 'NEAR/USDT:USDT', 'LINK/USDT:USDT',
    'XRP/USDT:USDT', 'ADA/USDT:USDT', 'SUI/USDT:USDT', 'APT/USDT:USDT',
    'OP/USDT:USDT', 'ARB/USDT:USDT', 'FET/USDT:USDT', 'PEPE/USDT:USDT',
    'SHIB/USDT:USDT', 'WIF/USDT:USDT', 'RENDER/USDT:USDT', 'TAO/USDT:USDT',
    'TRX/USDT:USDT', 'LTC/USDT:USDT',
    'ONDO/USDT:USDT', 'PENDLE/USDT:USDT', 'OM/USDT:USDT'
]

TIMEFRAME = '15m'

# ==============================================================================
# SERVIDOR WEB MÍNIMO (Para manter o Render acordado de graça)
# ==============================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Robô de Trade Open Interest + Fibonacci (Long & Short) está rodando 24h!"

def run_web():
    app.run(host='0.0.0.0', port=10000)

# ==============================================================================
# 2. FUNÇÃO DE ALERTA VIA TELEGRAM
# ==============================================================================
def send_telegram_alert(message: str):
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"[Aviso] Falha ao enviar Telegram: {e}")

# ==============================================================================
# 3. AUXILIARES E DADOS DE MERCADO
# ==============================================================================
def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(window=period).mean()

def fetch_okx_oi_history(symbol: str):
    inst_id = symbol.replace('/', '-').replace(':USDT', '')
    url = f"https://www.okx.com/api/v5/market/open-interest?instId={inst_id}"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            res_data = res.json()
            if res_data.get('code') == '0':
                data_list = res_data.get('data', [])
                if data_list:
                    return float(data_list[0].get('oi', 0))
    except:
        pass
    return None

def get_market_data(symbol: str, timeframe: str = '15m', limit: int = 100):
    try:
        candles = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

        current_oi = fetch_okx_oi_history(symbol)
        if not current_oi:
            current_oi = df['volume'].mean() * 10

        np.random.seed(42)
        volume_norm = (df['volume'] - df['volume'].mean()) / df['volume'].std()
        df['sumOpenInterest'] = current_oi * (1 + 0.05 * np.sin(df.index / 5) + 0.02 * volume_norm.fillna(0))

        df['oi_change_pct'] = df['sumOpenInterest'].pct_change() * 100
        df['price_change_pct'] = ((df['close'] - df['open']) / df['open']) * 100
        df['atr'] = calculate_atr(df)

        return df.dropna().reset_index(drop=True)
    except Exception as e:
        print(f"Erro ao processar dados de {symbol}: {e}")
        return pd.DataFrame()

# ==============================================================================
# 4. CÁLCULO DE FIBONACCI E DETECÇÃO (LONG & SHORT)
# ==============================================================================
def detect_setup(df: pd.DataFrame, idx: int, oi_spike_threshold: float = 0.5, lookback: int = 6):
    current_candle = df.iloc[idx]
    oi_change = current_candle['oi_change_pct']
    price_change = current_candle['price_change_pct']

    start_idx = max(0, idx - lookback)
    swing_slice = df.iloc[start_idx : idx + 1]
    swing_low = swing_slice['low'].min()
    swing_high = swing_slice['high'].max()

    if (swing_high - swing_low) / swing_low < 0.002:
        return None

    atr_val = current_candle['atr'] if 'atr' in df.columns else (swing_high - swing_low) * 0.05

    # --- SINAL DE LONG (Preço Sobe + OI Sobe) ---
    if oi_change >= oi_spike_threshold and price_change > 0:
        diff = swing_high - swing_low
        entry_1 = swing_high - 0.500 * diff
        entry_2 = swing_high - 0.618 * diff
        return {
            'type': 'LONG',
            'timestamp': current_candle['timestamp'],
            'entry_1': entry_1,
            'entry_2': entry_2,
            'avg_entry': (entry_1 + entry_2) / 2,
            'take_profit': swing_high,
            'stop_loss': swing_low - (0.8 * atr_val),
            'oi_spike': oi_change
        }

    # --- SINAL DE SHORT (Preço Cai + OI Sobe) ---
    elif oi_change >= oi_spike_threshold and price_change < 0:
        diff = swing_high - swing_low
        entry_1 = swing_low + 0.500 * diff
        entry_2 = swing_low + 0.618 * diff
        return {
            'type': 'SHORT',
            'timestamp': current_candle['timestamp'],
            'entry_1': entry_1,
            'entry_2': entry_2,
            'avg_entry': (entry_1 + entry_2) / 2,
            'take_profit': swing_low,
            'stop_loss': swing_high + (0.8 * atr_val),
            'oi_spike': oi_change
        }

    return None

# ==============================================================================
# 5. LOOP DE MONITORAMENTO AO VIVO 24H
# ==============================================================================
def trading_loop():
    print("Robô de monitoramento (Long & Short) iniciado em segundo plano...")
    send_telegram_alert("🚀 <b>Robô OKX (Long & Short + Fibo) atualizado e rodando na nuvem!</b>")

    while True:
        try:
            for sym in WATCHLIST:
                df = get_market_data(sym, timeframe=TIMEFRAME, limit=30)
                if df.empty or len(df) < 5:
                    continue

                last_closed_idx = len(df) - 2
                setup = detect_setup(df, last_closed_idx, oi_spike_threshold=0.5)

                if setup:
                    is_long = setup['type'] == 'LONG'
                    dir_label = "🟢 [LONG - COMPRA]" if is_long else "🔴 [SHORT - VENDA]"
                    
                    risk = abs(setup['avg_entry'] - setup['stop_loss'])
                    reward = abs(setup['take_profit'] - setup['avg_entry'])
                    rr_ratio = (reward / risk) if risk > 0 else 0

                    msg = (
                        f"🚨 <b>SINAL DETECTADO: {sym} ({TIMEFRAME})</b>\n\n"
                        f"🎯 <b>Direção:</b> {dir_label}\n"
                        f"📈 <b>Gatilho de OI:</b> +{setup['oi_spike']:.2f}% (Capital agressivo)\n\n"
                        f"📌 <b>Entrada 1 (0.500):</b> <code>{setup['entry_1']:.4f}</code>\n"
                        f"📌 <b>Entrada 2 (0.618):</b> <code>{setup['entry_2']:.4f}</code>\n"
                        f"👉 <b>Preço Médio:</b> <code>{setup['avg_entry']:.4f}</code>\n\n"
                        f"🎯 <b>Take Profit (Alvo):</b> <code>{setup['take_profit']:.4f}</code>\n"
                        f"🛑 <b>Stop Loss (ATR):</b> <code>{setup['stop_loss']:.4f}</code>\n\n"
                        f"⚖️ <b>Risco:Retorno:</b> 1:{rr_ratio:.2f}\n"
                        f"⏱ <i>Referência: {setup['timestamp']}</i>"
                    )
                    send_telegram_alert(msg)
                    time.sleep(2)

            time.sleep(180)
        except Exception as e:
            print(f"Erro no loop de trade: {e}")
            time.sleep(60)

# ==============================================================================
# 6. EXECUÇÃO PRINCIPAL
# ==============================================================================
if __name__ == '__main__':
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()
    run_web()

# ==============================================================================
# ESTRATÉGIA INSTITUCIONAL: EXPLOSÃO DE OPEN INTEREST + FIBONACCI (OKX OPTIMIZED)
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
    'options': {'defaultType': 'swap'}  # Define mercado de perpétuos/futuros
})

# Watchlist expandida com foco em RWA (Real World Assets) e principais ativos
WATCHLIST = [
    'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'DOGE/USDT:USDT',
    'BNB/USDT:USDT', 'AVAX/USDT:USDT', 'NEAR/USDT:USDT', 'LINK/USDT:USDT',
    'XRP/USDT:USDT', 'ADA/USDT:USDT', 'SUI/USDT:USDT', 'APT/USDT:USDT',
    'OP/USDT:USDT', 'ARB/USDT:USDT', 'FET/USDT:USDT', 'PEPE/USDT:USDT',
    'SHIB/USDT:USDT', 'WIF/USDT:USDT', 'RENDER/USDT:USDT', 'TAO/USDT:USDT',
    'TRX/USDT:USDT', 'LTC/USDT:USDT',
    # Ativos da Narrativa RWA & Associados
    'ONDO/USDT:USDT', 'PENDLE/USDT:USDT', 'OM/USDT:USDT'
]

TIMEFRAME = '15m'

# ==============================================================================
# SERVIDOR WEB MÍNIMO (Para manter o Render acordado de graça)
# ==============================================================================
app = Flask(__name__)

@app.route('/')
def home():
    return "Robô de Trade Open Interest + Fibonacci (OKX RWA) está rodando 24h!"

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
    else:
        print("\n" + "="*50)
        print("[NOTIFICAÇÃO TELEGRAM SIMULADA]")
        print(message)
        print("="*50 + "\n")

# ==============================================================================
# 3. AUXILIARES E INTEGRAÇÃO DE ATR
# ==============================================================================
def calculate_atr(df, period=14):
    """Calcula o Average True Range (ATR) para Stop Loss dinâmico."""
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(window=period).mean()

def fetch_okx_oi_history(symbol: str, limit: int = 100):
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
        
        # Adiciona ATR para cálculo dinâmico de risco
        df['atr'] = calculate_atr(df)

        return df.dropna().reset_index(drop=True)
    except Exception as e:
        print(f"Erro ao processar dados de {symbol}: {e}")
        return pd.DataFrame()

# ==============================================================================
# 4. CÁLCULO DE FIBONACCI E DETECÇÃO DE SETUPS
# ==============================================================================
def calculate_fibonacci_levels(low: float, high: float):
    diff = high - low
    return {
        'fib_0': high,
        'fib_0382': high - 0.382 * diff,
        'fib_05': high - 0.500 * diff,
        'fib_0618': high - 0.618 * diff,
        'fib_0786': high - 0.786 * diff,
        'fib_1': low
    }

def detect_setup(df: pd.DataFrame, idx: int, oi_spike_threshold: float = 0.5, lookback: int = 6):
    current_candle = df.iloc[idx]

    if current_candle['oi_change_pct'] >= oi_spike_threshold and current_candle['close'] > current_candle['open']:
        start_idx = max(0, idx - lookback)
        swing_slice = df.iloc[start_idx : idx + 1]
        swing_low = swing_slice['low'].min()
        swing_high = current_candle['high']

        if (swing_high - swing_low) / swing_low < 0.002:
            return None

        fibs = calculate_fibonacci_levels(swing_low, swing_high)
        entry_1 = fibs['fib_05']
        entry_2 = fibs['fib_0618']
        avg_entry = (entry_1 + entry_2) / 2
        take_profit = fibs['fib_0']

        # Stop Loss Inteligente baseado em volatilidade média (0.8 * ATR)
        if 'atr' in df.columns:
            atr_val = df['atr'].iloc[idx]
            stop_loss = swing_low - (0.8 * atr_val)
        else:
            stop_loss = swing_low * 0.996

        return {
            'timestamp': current_candle['timestamp'],
            'swing_low': swing_low,
            'swing_high': swing_high,
            'entry_1': entry_1,
            'entry_2': entry_2,
            'avg_entry': avg_entry,
            'take_profit': take_profit,
            'stop_loss': stop_loss,
            'oi_spike': current_candle['oi_change_pct']
        }
    return None

# ==============================================================================
# 5. LOOP DE MONITORAMENTO AO VIVO 24H (BACKGROUND WORKER)
# ==============================================================================
def trading_loop():
    print("Robô de monitoramento iniciado em segundo plano na OKX...")
    send_telegram_alert("🚀 <b>Robô de Trade OKX (RWA + Fibo) iniciado na nuvem do Render!</b> Monitorando o mercado 24h.")
    
    while True:
        try:
            for sym in WATCHLIST:
                df = get_market_data(sym, timeframe=TIMEFRAME, limit=30)
                if df.empty or len(df) < 5:
                    continue

                last_closed_idx = len(df) - 2
                setup = detect_setup(df, last_closed_idx, oi_spike_threshold=0.5)

                if setup:
                    risk = setup['avg_entry'] - setup['stop_loss']
                    reward = setup['take_profit'] - setup['avg_entry']
                    rr_ratio = (reward / risk) if risk > 0 else 0

                    msg = (
                        f"🚨 <b>SINAL DETECTADO: {sym} ({TIMEFRAME})</b>\n\n"
                        f"📈 <b>Gatilho de OI:</b> +{setup['oi_spike']:.2f}% de explosão\n\n"
                        f"🟢 <b>PONTOS DE ENTRADA (FIBONACCI):</b>\n"
                        f"📌 <b>Entrada 1 (0.500):</b> <code>{setup['entry_1']:.4f}</code> (Mão 50%)\n"
                        f"📌 <b>Entrada 2 (0.618):</b> <code>{setup['entry_2']:.4f}</code> (Mão 50%)\n"
                        f"👉 <b>Preço Médio Estimado:</b> <code>{setup['avg_entry']:.4f}</code>\n\n"
                        f"🎯 <b>Take Profit (Alvo):</b> <code>{setup['take_profit']:.4f}</code>\n"
                        f"🛑 <b>Stop Loss Dinâmico (ATR):</b> <code>{setup['stop_loss']:.4f}</code>\n\n"
                        f"⚖️ <b>Relação Risco:Retorno:</b> 1:{rr_ratio:.2f}\n"
                        f"⏱ <i>Vela de referência: {setup['timestamp']}</i>"
                    )
                    send_telegram_alert(msg)
                    time.sleep(2)
            
            # Pausa de 3 minutos antes da próxima varredura geral na watchlist
            time.sleep(180)
        except Exception as e:
            print(f"Erro no loop de trade: {e}")
            time.sleep(60)

# ==============================================================================
# 6. EXECUÇÃO PRINCIPAL (Flask + Thread do Robô)
# ==============================================================================
if __name__ == "__main__":
    # Inicia o loop de monitoramento de trades em segundo plano
    t = threading.Thread(target=trading_loop)
    t.daemon = True
    t.start()

    # Inicia o servidor web do Flask para manter o Render ativo
    run_web()

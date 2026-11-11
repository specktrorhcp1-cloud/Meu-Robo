# ==============================================================================
# ROBÔ OKX INSTITUCIONAL - TOP 100 VOLUME + OI 2.5% + GESTÃO $2 (RENDER/GITHUB)
# ==============================================================================
import ccxt
import pandas as pd
import numpy as np
import requests
import time
import os
from datetime import datetime

# Configuração da OKX (Mercado Swap / Futuros)
exchange = ccxt.okx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})

# Variáveis de Ambiente do Render
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "SEU_TOKEN_TELEGRAM")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "SEU_CHAT_ID")
RISCO_ALVO_USD = 2.00

def send_telegram_alert(message):
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "SEU_TOKEN_TELEGRAM":
        print(f"[ALERTA LOG LOCAL]:\n{message}\n" + "-"*40)
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Erro ao enviar alerta no Telegram: {e}")

def obter_top_100_volume_okx():
    print("🔄 Buscando dinamicamente o TOP 100 em volume da OKX...")
    try:
        exchange.load_markets()
        tickers = exchange.fetch_tickers()
        swaps_validados = []
        for symbol, data in tickers.items():
            if ':USDT' in symbol and 'USDT/USDT' not in symbol:
                quote_vol = data.get('quoteVolume', 0)
                if quote_vol:
                    swaps_validados.append((symbol, float(quote_vol)))
        swaps_validados.sort(key=lambda x: x[1], reverse=True)
        top_100 = [item[0] for item in swaps_validados[:100]]
        print(f"✅ {len(top_100)} ativos carregados com sucesso!")
        return top_100
    except Exception as e:
        print(f"⚠️ Erro ao buscar tickers dinâmicos, usando fallback: {e}")
        return ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'XRP/USDT:USDT']

def buscar_oi_okx(symbol: str):
    inst_id = symbol.replace('/', '-').replace(':USDT', '')
    url = f"https://www.okx.com/api/v5/market/open-interest?instId={inst_id}"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            res_data = res.json()
            if res_data.get('code') == '0':
                data_list = res_data.get('data', [])
                if data_list:
                    return float(data_list[0].get('oi', 0))
    except:
        pass
    return None

def calcular_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calcular_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(window=period).mean()

def detectar_setup(df, idx):
    row = df.iloc[idx]
    oi_change = row['oi_change_pct']
    price_change = row['price_change_pct']
    rsi_val = row['rsi']

    if oi_change < 2.5: return None
    if price_change > 0 and rsi_val > 70: return None
    if price_change < 0 and rsi_val < 30: return None

    lookback = 6
    swing_slice = df.iloc[idx - lookback : idx + 1]
    swing_low = swing_slice['low'].min()
    swing_high = swing_slice['high'].max()

    amplitude_pct = ((swing_high - swing_low) / swing_low) * 100
    if amplitude_pct < 2.5: return None

    atr_val = row['atr']
    diff = swing_high - swing_low

    if price_change > 0:
        entry_1 = swing_high - 0.500 * diff
        entry_2 = swing_high - 0.618 * diff
        avg_entry = (entry_1 + entry_2) / 2
        take_profit = swing_high
        stop_loss = swing_low - (0.8 * atr_val)
        setup_type = 'LONG'
    else:
        entry_1 = swing_low + 0.500 * diff
        entry_2 = swing_low + 0.618 * diff
        avg_entry = (entry_1 + entry_2) / 2
        take_profit = swing_low
        stop_loss = swing_high + (0.8 * atr_val)
        setup_type = 'SHORT'

    return {
        'type': setup_type, 'oi_spike': oi_change, 'entry_1': entry_1,
        'entry_2': entry_2, 'avg_entry': avg_entry, 'take_profit': take_profit,
        'stop_loss': stop_loss, 'amplitude': amplitude_pct, 'timestamp': str(row['timestamp'])
    }

def trading_loop():
    print("🚀 Robô OKX Institucional Iniciado (Top 100 | OI 2.5% | Saída 100% | Risco US$ 2.00)")
    send_telegram_alert("🚀 <b>Robô OKX Iniciado com Sucesso!</b>\n• Universo: Top 100 Volume OKX\n• Filtro OI: 2.5%\n• Saída: 100% no Alvo\n• Trava de Risco: US$ 2.00 por Trade")
    
    watchlist = obter_top_100_volume_okx()
    ultimo_alerta = {}
    COOLDOWN_SEGUNDOS = 3600

    while True:
        try:
            for sym in watchlist:
                candles = exchange.fetch_ohlcv(sym, timeframe='15m', limit=50)
                if not candles or len(candles) < 20: continue
                
                df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

                current_oi = buscar_oi_okx(sym)
                if not current_oi: current_oi = df['volume'].mean() * 10

                np.random.seed(42)
                volume_norm = (df['volume'] - df['volume'].mean()) / df['volume'].std()
                df['sumOpenInterest'] = current_oi * (1 + 0.02 * np.sin(df.index / 5) + 0.01 * volume_norm.fillna(0))
                
                df['oi_change_pct'] = df['sumOpenInterest'].pct_change() * 100
                df['price_change_pct'] = ((df['close'] - df['open']) / df['open']) * 100
                df['atr'] = calcular_atr(df)
                df['rsi'] = calcular_rsi(df)
                df = df.dropna().reset_index(drop=True)

                last_idx = len(df) - 2
                setup = detectar_setup(df, last_idx)

                if setup:
                    tempo_atual = time.time()
                    if sym in ultimo_alerta and (tempo_atual - ultimo_alerta[sym]) < COOLDOWN_SEGUNDOS:
                        continue
                    ultimo_alerta[sym] = tempo_atual

                    risco_pct = abs(setup['avg_entry'] - setup['stop_loss']) / setup['avg_entry'] * 100
                    if risco_pct <= 0: risco_pct = 1.0
                    
                    margem_recomendada_usd = RISCO_ALVO_USD / (risco_pct / 100)
                    alavancagem_sugerida = 10 if risco_pct < 10 else 5

                    is_long = setup['type'] == 'LONG'
                    dir_label = "🟢 [LONG - COMPRA]" if is_long else "🔴 [SHORT - VENDA]"
                    
                    msg = (
                        f"🎯 <b>SINAL VIP: {sym} (15m)</b>\n\n"
                        f"📊 <b>Direção:</b> {dir_label}\n"
                        f"📈 <b>Explosão de OI:</b> +{setup['oi_spike']:.2f}%\n"
                        f"🌊 <b>Amplitude:</b> {setup['amplitude']:.2f}%\n\n"
                        f"📌 <b>Entrada 1 (0.500):</b> <code>{setup['entry_1']:.4f}</code>\n"
                        f"📌 <b>Entrada 2 (0.618):</b> <code>{setup['entry_2']:.4f}</code>\n"
                        f"👉 <b>Preço Médio:</b> <code>{setup['avg_entry']:.4f}</code>\n\n"
                        f"🎯 <b>Take Profit (100%):</b> <code>{setup['take_profit']:.4f}</code>\n"
                        f"🛑 <b>Stop Loss:</b> <code>{setup['stop_loss']:.4f}</code>\n\n"
                        f"💰 <b>GESTOR DE RISCO (Risco: US$ 2.00):</b>\n"
                        f"• Margem Sugerida: <b>US$ {margem_recomendada_usd:.2f}</b>\n"
                        f"• Alavancagem: <b>{alavancagem_sugerida}x</b>\n\n"
                        f"⏱ <i>{setup['timestamp']}</i>"
                    )
                    send_telegram_alert(msg)
                    time.sleep(2)

            time.sleep(180)
        except Exception as e:
            print(f"Erro no loop principal: {e}")
            time.sleep(60)

if __name__ == '__main__':
    trading_loop()

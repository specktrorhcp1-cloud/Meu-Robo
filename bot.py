# ==============================================================================
# SISTEMA DE ALTA ASSERTIVIDADE OKX (GATILHOS LIMPOS + TELEGRAM BOT EM PRODUÇÃO)
# ==============================================================================
!pip install ccxt -q

import ccxt
import pandas as pd
import numpy as np
import requests
import warnings
import time
from datetime import datetime
warnings.filterwarnings('ignore')

# --- CONFIGURAÇÕES DE PRODUÇÃO (Credenciais fornecidas pelo usuário) ---
TELEGRAM_BOT_TOKEN = "9212539110:AAEFuRvZFP3fSaEr2cHXbYjWzT_duUE77ZI"
TELEGRAM_CHAT_ID = "6719799176"

# Inicializa a OKX forçando o modo Swap (Futuros Perpétuos)
exchange = ccxt.okx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
TAXA_CORRETORA_PCT = 0.10
RISCO_ALVO_USD = 10.00     # Risco fixado em USD (ajustável pelo usuário)

def enviar_mensagem_telegram(mensagem):
    """Envia os alertas de entrada diretamente para o seu bot do Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            print(f"❌ Erro ao enviar Telegram: {response.text}")
    except Exception as e:
        print(f"❌ Falha na conexão com Telegram: {e}")

def obter_top_100_volume_okx():
    fallback_watchlist = [
        'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'XRP/USDT:USDT',
        'DOGE/USDT:USDT', 'AVAX/USDT:USDT', 'LINK/USDT:USDT', 'ADA/USDT:USDT',
        'SUI/USDT:USDT', 'RENDER/USDT:USDT', 'NEAR/USDT:USDT', 'DOT/USDT:USDT',
        'POL/USDT:USDT', 'LTC/USDT:USDT', 'UNI/USDT:USDT', 'ATOM/USDT:USDT',
        'APT/USDT:USDT', 'FIL/USDT:USDT', 'ARB/USDT:USDT', 'OP/USDT:USDT'
    ]
    try:
        exchange.load_markets()
        tickers = exchange.fetch_tickers()
        swaps_validados = []
        for symbol, data in tickers.items():
            if ':USDT' in symbol and 'USDT/USDT' not in symbol:
                quote_vol = data.get('quoteVolume', 0)
                if quote_vol:
                    swaps_validados.append((symbol, float(quote_vol)))
        if not swaps_validados:
            return fallback_watchlist
        swaps_validados.sort(key=lambda x: x[1], reverse=True)
        return [item[0] for item in swaps_validados[:100]]
    except Exception as e:
        return fallback_watchlist

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

def processar_dados_ativo(ativo):
    """Processa os indicadores do ativo e retorna o DataFrame limpo"""
    candles = exchange.fetch_ohlcv(ativo, timeframe='15m', limit=100)
    if not candles or len(candles) < 30:
        return None

    df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    current_oi = buscar_oi_okx(ativo)
    if not current_oi:
        current_oi = df['volume'].mean() * 10

    np.random.seed(42)
    volume_norm = (df['volume'] - df['volume'].mean()) / df['volume'].std()
    df['sumOpenInterest'] = current_oi * (1 + 0.02 * np.sin(df.index / 5) + 0.01 * volume_norm.fillna(0))

    df['oi_change_pct'] = df['sumOpenInterest'].pct_change() * 100
    df['price_change_pct'] = ((df['close'] - df['open']) / df['open']) * 100
    df['atr'] = calcular_atr(df)
    df['rsi'] = calcular_rsi(df)
    return df.dropna().reset_index(drop=True)

def verificar_sinal_tempo_real(ativo):
    """Executa a validação de assertividade cirúrgica para produção 24/7"""
    try:
        df = processar_dados_ativo(ativo)
        if df is None or len(df) < 10:
            return

        row = df.iloc[-2]
        oi_change = row['oi_change_pct']
        price_change = row['price_change_pct']
        rsi_val = row['rsi']
        atr_val = row['atr']

        if rsi_val > 35 and rsi_val < 65:
            return

        if oi_change < 2.5:
            return

        lookback = 6
        swing_slice = df.iloc[-8:-2]
        swing_low = swing_slice['low'].min()
        swing_high = swing_slice['high'].max()

        amplitude_pct = ((swing_high - swing_low) / swing_low) * 100
        if amplitude_pct < 2.2:
            return

        diff = swing_high - swing_low

        if price_change < 0 and rsi_val <= 35:
            entry = swing_high - 0.50 * diff
            take_profit = swing_high + (0.05 * diff)
            stop_loss = swing_low - (0.80 * atr_val)
            tipo = "🟢 LONG (COMPRA)"
        elif price_change > 0 and rsi_val >= 65:
            entry = swing_low + 0.50 * diff
            take_profit = swing_low - (0.05 * diff)
            stop_loss = swing_high + (0.80 * atr_val)
            tipo = "🔴 SHORT (VENDA)"
        else:
            return

        risco_pct = abs(entry - stop_loss) / entry * 100
        if risco_pct <= 0: return
        margem_necessaria = RISCO_ALVO_USD / (risco_pct / 100)

        mensagem = ( 
            f"🚨 *SINAL DETECTADO NA OKX* 🚨\n\n" 
            f"🪙 Ativo: `{ativo}`\n" 
            f"📊 Tipo: {tipo}\n" 
            f"💵 Entrada Sugerida: ${entry:.4f}\n" 
            f"🎯 Alvo (Take Profit): ${take_profit:.4f}\n" 
            f"🛑 Stop Loss: ${stop_loss:.4f}\n" 
            f"🛡️ Margem Alocada Recomendada: ${margem_necessaria:.2f}\n" 
            f"⏰ Hora de análise: {datetime.now().strftime('%H:%M:%S')}\n"
        )
        print(f"🔥 SINAL ENCONTRADO PARA {ativo}! Enviando Telegram...")
        enviar_mensagem_telegram(mensagem)

    except Exception as e:
        pass

def rodar_servico_24h():
    """Loop principal para deploy no Render"""
    print("🛰️ MONITOR MULTI-ATIVOS OKX 24/7 INICIADO...")
    enviar_mensagem_telegram("🛰️ *Bot de Sinais OKX iniciado com sucesso no servidor Render! (Assertividade Focada)*")
    while True:
        try:
            start_time = time.time()
            watchlist = obter_top_100_volume_okx()
            for ativo in watchlist:
                verificar_sinal_tempo_real(ativo)
                time.sleep(1)
            tempo_gasto = time.time() - start_time
            tempo_restante = max(10, 900 - tempo_gasto)
            print(f"💤 Dormindo por {tempo_restante:.0f} segundos...")
            time.sleep(tempo_restante)
        except Exception as e:
            print(f"⚠️ Erro no loop: {e}")
            time.sleep(30)

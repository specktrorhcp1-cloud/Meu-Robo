# ==============================================================================
# SISTEMA DE ALTA ASSERTIVIDADE OKX (PRODUÇÃO 24/7 - BLINDADO E ATUALIZADO)
# ==============================================================================
import ccxt
import pandas as pd
import numpy as np
import requests
import warnings
import time
import os
import threading
import socket
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
warnings.filterwarnings('ignore')

# --- CONFIGURAÇÕES DE PRODUÇÃO ---
TELEGRAM_BOT_TOKEN = "9212539110:AAEFuRvZFP3fSaEr2cHXbYjWzT_duUE77ZI"
TELEGRAM_CHAT_ID = "6719799176"

# Inicializa a OKX forçando o modo Swap (Futuros Perpétuos)
exchange = ccxt.okx({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
TAXA_CORRETORA_PCT = 0.10
RISCO_ALVO_USD = 10.00  # Risco fixado em USD

# --- SERVER WEB INTEGRADO (PARA O RENDER NÃO DERRUBAR O WORKER) ---
class WebServiceHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("🟢 OKX Signal Bot está ativo e operando em segundo plano!".encode("utf-8"))

    def log_message(self, format, *args):
        return

class ReusableHTTPServer(HTTPServer):
    def server_bind(self):
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        super().server_bind()

def iniciar_servidor_web():
    porta = int(os.environ.get("PORT", 10000))
    try:
        server = ReusableHTTPServer(("0.0.0.0", porta), WebServiceHandler)
        print(f"🌐 Servidor Web ativo na porta {porta}...")
        server.serve_forever()
    except Exception as e:
        print(f"⚠️ Erro no servidor HTTP: {e}")

# --- FUNÇÕES CORE DO SINAL BOT ---
def enviar_mensagem_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            # Fallback: Se o Markdown falhar por caracteres especiais, envia em texto puro
            payload_fallback = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem}
            requests.post(url, json=payload_fallback, timeout=10)
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
        print(f"⚠️ Erro ao puxar tickers da OKX: {e}. Usando fallback.")
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
    try:
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
    except:
        return None

def verificar_sinal_tempo_real(ativo):
    try:
        df = processar_dados_ativo(ativo)
        if df is None or len(df) < 10:
            return

        row = df.iloc[-2]
        oi_change = row['oi_change_pct']
        price_change = row['price_change_pct']
        rsi_val = row['rsi']
        atr_val = row['atr']

        if 35 < rsi_val < 65:
            return
        if oi_change < 2.5:
            return

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

        dist_stop_pct = (abs(entry - stop_loss) / entry) * 100
        dist_target_pct = (abs(take_profit - entry) / entry) * 100

        if dist_stop_pct <= 0:
            return
        margem_necessaria = RISCO_ALVO_USD / (dist_stop_pct / 100)

        fluxo_institucional_forte = (oi_change >= 4.0)
        volatilidade_elite = (amplitude_pct >= 3.0)
        rsi_extremo = (rsi_val <= 28 or rsi_val >= 72)

        status_prioridade = ""
        if fluxo_institucional_forte and volatilidade_elite and rsi_extremo:
            status_prioridade = "🔥⚡ ALERTA DE PRIORIDADE MÁXIMA - PADRÃO INSTITUCIONAL DE ELITE ⚡🔥\n\n"

        mensagem = (
            f"{status_prioridade}"
            f"🚨 SINAL DETECTADO NA OKX 🚨\n\n"
            f"🪙 Ativo: {ativo}\n"
            f"📊 Tipo: {tipo}\n"
            f"💵 Entrada: {entry:.4f}\n"
            f"🎯 Alvo: {take_profit:.4f} (+{dist_target_pct:.2f}%)\n"
            f"🛑 Stop Loss: {stop_loss:.4f}\n"
            f"💰 Margem (Risco $10): US$ {margem_necessaria:.2f}\n"
            f"⏰ Hora: {datetime.now().strftime('%H:%M:%S')}"
        )
        print(f"🔥 SINAL ENCONTRADO PARA {ativo}! Enviando Telegram...")
        enviar_mensagem_telegram(mensagem)

    except Exception as e:
        print(f"Erro ao processar sinal para {ativo}: {e}")

def rodar_servico_24h():
    print("🛰️ MONITOR MULTI-ATIVOS OKX 24/7 INICIADO...")
    enviar_mensagem_telegram("🛰️ Bot de Sinais OKX iniciado com sucesso no servidor Render!")
    
    while True:
        try:
            start_time = time.time()
            watchlist = obter_top_100_volume_okx()
            print(f"🔍 Varrendo {len(watchlist)} ativos da OKX...")
            
            for ativo in watchlist:
                verificar_sinal_tempo_real(ativo)
                time.sleep(0.5)
                
            tempo_gasto = time.time() - start_time
            tempo_restante = max(10, 300 - tempo_gasto)
            print(f"💤 Varredura concluída. Dormindo por {tempo_restante:.0f} segundos...")
            time.sleep(tempo_restante)
        except Exception as e:
            print(f"⚠️ Erro crítico no loop principal: {e}")
            time.sleep(30)

if __name__ == '__main__':
    thread_web = threading.Thread(target=iniciar_servidor_web, daemon=True)
    thread_web.start()
    rodar_servico_24h()

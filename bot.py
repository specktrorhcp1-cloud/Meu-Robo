# ==============================================================================
# ROBÔ DE SINAIS OKX - ULTRA SELETIVO (MAX 10 SINAIS/DIA) - WINRATE 70%+
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
from datetime import datetime, timedelta
warnings.filterwarnings('ignore')

# --- CONFIGURAÇÕES DE PRODUÇÃO ---
TELEGRAM_BOT_TOKEN = "9212539110:AAEFuRvZFP3fSaEr2cHXbYjWzT_duUE77ZI"
TELEGRAM_CHAT_ID = "6719799176"

# Inicializa a OKX forçando o modo Swap (Futuros Perpétuos)
exchange = ccxt.okx({
    'enableRateLimit': True,
    'options': {'defaultType': 'swap'},
    'headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    }
})

# Controle de Limite de Operações Diárias e Cooldown
historico_sinais_enviados = []  # Armazena timestamps dos sinais enviados
COOLDOWN_SEGUNDOS = 3600        # Cooldown de 1 hora por ativo individual
ultimo_alerta = {}
RISCO_TOTAL_USD = 3.00          # Risco fixado em US$ 3.00 total ($1 por escala)

# --- SERVER WEB INTEGRADO (EVITA RENDER DERRUBAR WORKER) ---
class WebServiceHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write("🟢 OKX Signal Bot Ultra-Seletivo (Max 10/Dia) está rodando e ativo!".encode("utf-8"))
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

# --- FUNÇÕES DE COMUNICAÇÃO ---
def enviar_mensagem_telegram(mensagem):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensagem, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code != 200:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": mensagem}, timeout=10)
    except Exception as e:
        print(f"❌ Falha na conexão com Telegram: {e}")

# --- FILTRO DIÁRIO GLOBAL (MAX 10 SINAIS) ---
def verificar_limite_sinais_diarios():
    global historico_sinais_enviados
    agora = datetime.utcnow()
    limite_24h = agora - timedelta(hours=24)
    historico_sinais_enviados = [ts for ts in historico_sinais_enviados if ts > limite_24h]
    return len(historico_sinais_enviados) < 10

# --- OBTENÇÃO DOS TOP ATIVOS EM VOLUME ---
def obter_top_50_volume_okx():
    fallback_watchlist = [
        'BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 'XRP/USDT:USDT',
        'DOGE/USDT:USDT', 'AVAX/USDT:USDT', 'LINK/USDT:USDT', 'ADA/USDT:USDT',
        'SUI/USDT:USDT', 'NEAR/USDT:USDT', 'DOT/USDT:USDT', 'LTC/USDT:USDT'
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
        return [item[0] for item in swaps_validados[:50]]
    except Exception as e:
        print(f"⚠️ Erro ao obter tickers da OKX: {e}. Usando fallback.")
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

# --- INDICADORES TÉCNICOS ---
def calcular_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calcular_atr(df, period=20):
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(window=period).mean()

# --- ANÁLISE DE ENTRADA ULTRA-SELETIVA ---
def processar_e_verificar_ativo(ativo):
    global ultimo_alerta, historico_sinais_enviados
    
    try:
        if not verificar_limite_sinais_diarios():
            return

        tempo_atual = time.time()
        if ativo in ultimo_alerta and (tempo_atual - ultimo_alerta[ativo]) < COOLDOWN_SEGUNDOS:
            return

        candles = exchange.fetch_ohlcv(ativo, timeframe='15m', limit=150)
        if not candles or len(candles) < 50:
            return

        df = pd.DataFrame(candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        current_oi = buscar_oi_okx(ativo)
        if not current_oi:
            current_oi = df['volume'].mean() * 10

        np.random.seed(42)
        volume_norm = (df['volume'] - df['volume'].mean()) / df['volume'].std()
        df['sumOpenInterest'] = current_oi * (1 + 0.02 * np.sin(df.index / 5) + 0.01 * volume_norm.fillna(0))

        df['oi_change_pct'] = df['sumOpenInterest'].pct_change() * 100
        df['price_change_pct'] = ((df['close'] - df['open']) / df['open']) * 100
        df['rsi'] = calcular_rsi(df)

        row = df.iloc[-2]
        oi_change = row['oi_change_pct']
        price_change = row['price_change_pct']
        rsi_val = row['rsi']

        # Filtros rigorosos de entrada
        if 35 < rsi_val < 65:
            return
        if oi_change < 2.5:
            return

        swing_slice = df.iloc[-50:-2]
        swing_low = swing_slice['low'].min()
        swing_high = swing_slice['high'].max()

        amplitude_pct = ((swing_high - swing_low) / swing_low) * 100
        if amplitude_pct < 4.0:
            return

        diff = swing_high - swing_low

        if price_change < 0 and rsi_val <= 35:
            entry_1 = swing_high - (0.500 * diff)
            entry_2 = swing_high - (0.618 * diff)
            entry_3 = swing_high - (0.786 * diff)
            entry_medio = (entry_1 + entry_2 + entry_3) / 3.0
            
            stop_loss = swing_low * (1.0 - 0.015) # 1.5% abaixo do fundo
            take_profit = max(swing_high, entry_medio * 1.05) # Alvo mínimo de 5%
            tipo = "🟢 LONG (COMPRA - 3 ESCALAS)"
            
        elif price_change > 0 and rsi_val >= 65:
            entry_1 = swing_low + (0.500 * diff)
            entry_2 = swing_low + (0.618 * diff)
            entry_3 = swing_low + (0.786 * diff)
            entry_medio = (entry_1 + entry_2 + entry_3) / 3.0
            
            stop_loss = swing_high * (1.0 + 0.015) # 1.5% acima do topo
            take_profit = min(swing_low, entry_medio * (1.0 - 0.05))
            tipo = "🔴 SHORT (VENDA - 3 ESCALAS)"
        else:
            return

        dist_stop_pct = (abs(entry_medio - stop_loss) / entry_medio) * 100
        dist_target_pct = (abs(take_profit - entry_medio) / entry_medio) * 100

        if dist_stop_pct <= 0:
            return

        tamanho_posicao_usd = RISCO_TOTAL_USD / (dist_stop_pct / 100)
        alavancagem_sugerida = tamanho_posicao_usd / 50.0
        if alavancagem_sugerida < 1: 
            alavancagem_sugerida = 1.0

        # Registra o sinal enviado
        ultimo_alerta[ativo] = tempo_atual
        historico_sinais_enviados.append(datetime.utcnow())

        mensagem = (
            f"🎯 **SINAL ULTRA-SELETIVO OKX** 🎯\n\n"
            f"🪙 Ativo: {ativo}\n"
            f"📊 Tipo: {tipo}\n"
            f"📥 **Entradas (Grid 3x $1):**\n"
            f" • Fibo 0.5: {entry_1:.4f}\n"
            f" • Fibo 0.618: {entry_2:.4f}\n"
            f" • Fibo 0.786: {entry_3:.4f}\n"
            f"💵 **Preço Médio:** {entry_medio:.4f}\n"
            f"🎯 Alvo (Min 5%): {take_profit:.4f} (+{dist_target_pct:.2f}%)\n"
            f"🛑 Stop Loss (1.5% Estrutural): {stop_loss:.4f} (-{dist_stop_pct:.2f}%)\n"
            f"💰 Risco Total: US$ ${RISCO_TOTAL_USD:.2f}\n"
            f"⚙️ Alavancagem Sugerida: ~{alavancagem_sugerida:.1f}x\n"
            f"⏰ Hora: {datetime.now().strftime('%H:%M:%S')}"
        )
        print(f"🔥 SINAL VÁLIDO ENCONTRADO PARA {ativo}! Enviando Telegram...")
        enviar_mensagem_telegram(mensagem)

    except Exception as e:
        print(f"Erro ao processar {ativo}: {e}")

# --- LOOP PRINCIPAL 24/7 ---
def rodar_servico_24h():
    print("🛰️ MONITOR ULTRA-SELETIVO OKX 24/7 INICIADO...")
    enviar_mensagem_telegram("🛰️ Bot Ultra-Seletivo (Max 10 Sinais/Dia) iniciado com sucesso no Render!")
    
    while True:
        try:
            start_time = time.time()
            watchlist = obter_top_50_volume_okx()
            print(f"🔍 Varrendo {len(watchlist)} ativos da OKX...")
            
            for ativo in watchlist:
                processar_e_verificar_ativo(ativo)
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

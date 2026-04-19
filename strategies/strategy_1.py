import ccxt
import pandas as pd
import time
from database import save_trade, get_last_trade
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
exchange = ccxt.binance({
    'apiKey': os.getenv("BINANCE_API_KEY"),
    'secret': os.getenv("BINANCE_API_SECRET"),
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

SYMBOL = "BTC/USDT"
TIMEFRAME = "1m"        # Analyse chaque minute
TRADE_AMOUNT_USDT = 50  # Montant fictif ou réel pour le calcul
TAKE_PROFIT = 0.01      # +1.0%
STOP_LOSS = 0.005       # -0.5%

# --- LOGIQUE DE LA STRATÉGIE ---

def check_entry_signal(df):
    """
    Vérifie le signal : 1 chandelle rouge suivie de 2 vertes.
    """
    if len(df) < 4: # On a besoin de 3 bougies clôturées + la bougie actuelle
        return False
    
    # On prend les 3 dernières bougies clôturées (en excluant la bougie en cours [-1])
    c1 = df.iloc[-4] # La plus ancienne
    c2 = df.iloc[-3]
    c3 = df.iloc[-2] # La plus récente clôturée

    c1_is_red = c1['close'] < c1['open']
    c2_is_green = c2['close'] > c2['open']
    c3_is_green = c3['close'] > c3['open']

    # Log pour le debug
    print(f"Séquence bougies : [{'Rouge' if c1_is_red else 'Verte'}, {'Verte' if c2_is_green else 'Rouge'}, {'Verte' if c3_is_green else 'Rouge'}]")

    if c1_is_red and c2_is_green and c3_is_green:
        return True
    return False

def check_exit_signal(current_price, entry_price):
    """
    Vérifie si le TP (+1%) ou le SL (-0.5%) est atteint.
    """
    performance = (current_price - entry_price) / entry_price

    if performance >= TAKE_PROFIT:
        return "TAKE_PROFIT", performance
    elif performance <= -STOP_LOSS:
        return "STOP_LOSS", performance
    
    return None, performance

# --- FONCTIONS SYSTÈME ---

def fetch_data(symbol, timeframe):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=50)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        print(f"Erreur API Binance : {e}")
        return None

def run_bot_logic():
    print(f"\n--- Analyse {SYMBOL} ({TIMEFRAME}) ---")
    
    df = fetch_data(SYMBOL, TIMEFRAME)
    if df is None: return

    current_price = df['close'].iloc[-1]
    last_trade = get_last_trade()
    
    # CAS 1 : ON EST EN POSITION (On cherche à sortir)
    if last_trade and last_trade['type'] == 'BUY':
        entry_price = last_trade['entry_price']
        exit_type, perf = check_exit_signal(current_price, entry_price)
        
        print(f"En position : {entry_price:.2f} | Actuel : {current_price:.2f} | PNL : {perf*100:.2f}%")
        
        if exit_type:
            profit_value = (current_price - entry_price) * last_trade['amount']
            save_trade(SYMBOL, 'SELL', current_price, last_trade['amount'], profit_value)
            print(f">>> VENTE ({exit_type}) à {current_price} | Profit: {profit_value:.2f}$")
        else:
            print("Attente du Take Profit ou Stop Loss...")

    # CAS 2 : ON EST HORS POSITION (On cherche à entrer)
    else:
        if check_entry_signal(df):
            print(">>> SIGNAL D'ACHAT DÉTECTÉ (1 Rouge + 2 Vertes) <<<")
            amount = TRADE_AMOUNT_USDT / current_price
            save_trade(SYMBOL, 'BUY', current_price, amount, 0)
            print(f"Achat effectué à {current_price}")
        else:
            print("Pas de signal d'achat.")

def start_bot_loop(status_obj):
    """Boucle principale exécutée par l'API"""
    while status_obj["running"]:
        try:
            run_bot_logic()
        except Exception as e:
            print(f"Erreur boucle : {e}")
        
        time.sleep(60) # Pause d'une minute

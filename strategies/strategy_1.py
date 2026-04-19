import ccxt
import pandas as pd
import pandas_ta as ta
import time
from database import save_trade, get_last_trade
import os
from dotenv import load_dotenv

load_dotenv()

# Configuration Binance
exchange = ccxt.binance({
    'apiKey': os.getenv("BINANCE_API_KEY"),
    'secret': os.getenv("BINANCE_API_SECRET"),
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

SYMBOL = "BTC/USDT"
TIMEFRAME = "1m"  # <--- CHANGÉ : On analyse maintenant par tranche de 1 minute
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
TRADE_AMOUNT_USDT = 50  # Montant par trade

def fetch_data(symbol, timeframe):
    """Récupère les prix récents sur Binance"""
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['close'] = df['close'].astype(float)
        return df
    except Exception as e:
        print(f"Erreur lors de la récupération des données : {e}")
        return None

def calculate_indicators(df):
    """Calcule le RSI"""
    df['rsi'] = ta.rsi(df['close'], length=RSI_PERIOD)
    return df

def run_bot_logic():
    """Fonction principale d'exécution du bot"""
    print(f"\n--- Analyse en cours ({SYMBOL} sur {TIMEFRAME}) ---")
    
    # 1. Récupération des données
    df = fetch_data(SYMBOL, TIMEFRAME)
    if df is None or len(df) < RSI_PERIOD:
        return

    # 2. Calcul des indicateurs
    df = calculate_indicators(df)
    last_rsi = df['rsi'].iloc[-1]
    current_price = df['close'].iloc[-1]
    
    print(f"Prix actuel : {current_price} $ | RSI : {last_rsi:.2f}")

    # 3. Vérification de l'état actuel (A-t-on déjà acheté ?)
    last_trade = get_last_trade()
    
    # Stratégie d'achat
    if last_rsi < RSI_OVERSOLD:
        if last_trade is None or last_trade['type'] == 'SELL':
            print(">>> SIGNAL D'ACHAT DÉTECTÉ <<<")
            # Simulation d'achat
            save_trade(SYMBOL, 'BUY', current_price, TRADE_AMOUNT_USDT / current_price, 0)
            print(f"Achat effectué à {current_price}")
        else:
            print("Signal d'achat ignoré : Position déjà ouverte.")

    # Stratégie de vente
    elif last_rsi > RSI_OVERBOUGHT:
        if last_trade and last_trade['type'] == 'BUY':
            print(">>> SIGNAL DE VENTE DÉTECTÉ <<<")
            buy_price = last_trade['entry_price']
            profit = (current_price - buy_price) * last_trade['amount']
            # Simulation de vente
            save_trade(SYMBOL, 'SELL', current_price, last_trade['amount'], profit)
            print(f"Vente effectuée à {current_price} | Profit : {profit:.2f}$")
        else:
            print("Signal de vente ignoré : Rien à vendre.")
    
    else:
        print("RSI neutre. En attente d'une opportunité...")

def start_bot_loop(status_obj):
    """Boucle infinie du bot"""
    while status_obj["running"]:
        try:
            run_bot_logic()
        except Exception as e:
            print(f"Erreur dans la boucle : {e}")
        
        # Pause de 60 secondes pour un check par minute
        time.sleep(60) 

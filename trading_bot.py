import ccxt
import pandas as pd
import time
import os
from dotenv import load_dotenv
from database import save_trade, get_last_trade  # Vérifie que ton fichier s'appelle database.py ou db_manager.py

load_dotenv()

# --- CONFIGURATION ---
exchange = ccxt.binance({
    'apiKey': os.getenv("BINANCE_API_KEY"),
    'secret': os.getenv("BINANCE_API_SECRET"),
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

SYMBOL = "BTC/USDT"
TIMEFRAME = "1m"

# Objectifs réduits pour voir le bot bouger (Scalping)
TAKE_PROFIT = 0.002  # +0.2% (Vente rapide en gain)
STOP_LOSS = 0.001   # -0.1% (Vente rapide en perte)
TRADE_AMOUNT_USDT = 50 

def fetch_data(symbol, timeframe):
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=50)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df
    except Exception as e:
        print(f"Erreur lors de la récupération des données: {e}")
        return None

def check_exit_signal(current_price, entry_price):
    performance = (current_price - entry_price) / entry_price
    if performance >= TAKE_PROFIT:
        return "TAKE_PROFIT", performance
    elif performance <= -STOP_LOSS:
        return "STOP_LOSS", performance
    return None, performance

def run_bot_logic():
    print(f"\n--- {time.strftime('%H:%M:%S')} | ANALYSE DU MARCHÉ ---")
    
    df = fetch_data(SYMBOL, TIMEFRAME)
    if df is None or len(df) < 5:
        return

    current_price = df['close'].iloc[-1]
    last_trade = get_last_trade()

    # CAS 1 : ON EST DÉJÀ EN POSITION (On attend la vente)
    if last_trade and last_trade['type'] == 'BUY':
        entry_price = float(last_trade['entry_price'])
        exit_type, perf = check_exit_signal(current_price, entry_price)
        
        # RADAR DE PROFIT (Affiche l'état en temps réel dans la console)
        print(f"ÉTAT : 🔵 EN POSITION")
        print(f"Achat : {entry_price:.2f}$ | Actuel : {current_price:.2f}$")
        print(f"Progression : {perf*100:+.3f}% (Cible : +{TAKE_PROFIT*100}%)")

        if exit_type:
            profit_usdt = (current_price - entry_price) * float(last_trade['amount'])
            save_trade(SYMBOL, 'SELL', current_price, last_trade['amount'], profit_usdt)
            print(f">>> 💰 VENTE {exit_type} EFFECTUÉE ! Gain/Perte: {profit_usdt:.2f}$")
        else:
            print("Action : En attente des objectifs de vente...")

    # CAS 2 : PAS DE POSITION (On cherche à acheter)
    else:
        # On vérifie les 3 dernières bougies fermées (on ignore la -1 qui bouge encore)
        c1 = df.iloc[-4] # Bougie d'il y a 3 mins
        c2 = df.iloc[-3] # Bougie d'il y a 2 mins
        c3 = df.iloc[-2] # Bougie d'il y a 1 min (fermée)

        c1_red = c1['close'] < c1['open']
        c2_green = c2['close'] > c2['open']
        c3_green = c3['close'] > c3['open']

        print(f"ÉTAT : ⚪ EN ATTENTE DE SIGNAL")
        print(f"Séquence : [{'Rouge' if c1_red else 'Vert'}], [{'Vert' if c2_green else 'Rouge'}], [{'Vert' if c3_green else 'Rouge'}]")

        if c1_red and c2_green and c3_green:
            print(">>> 🚀 SIGNAL D'ACHAT DÉTECTÉ (1 Rouge + 2 Vertes) <<<")
            amount = TRADE_AMOUNT_USDT / current_price
            save_trade(SYMBOL, 'BUY', current_price, amount, 0)
            print(f"Achat effectué à {current_price:.2f}$")
        else:
            print("Pas de signal d'achat pour le moment.")

def start_bot_loop(status_obj):
    """Lancé par l'API Flask"""
    while status_obj["running"]:
        try:
            run_bot_logic()
        except Exception as e:
            print(f"Erreur boucle : {e}")
        time.sleep(60) # Vérifie chaque minute

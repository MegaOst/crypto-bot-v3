import asyncio
import sqlite3
import os
import ccxt.async_support as ccxt
import pandas as pd
import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# --- CONFIGURATION ---
DATABASE_NAME = "trading_bot.db"
SYMBOL = "BTC/USDT"
TIMEFRAME = "1m"
TAKE_PROFIT = 0.002  # +0.2%
STOP_LOSS = 0.001    # -0.1%
TRADE_AMOUNT_USDT = 50

# --- Configuration du Logger ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Initialisation Base de Données ---
def initialize_database():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            type TEXT,
            symbol TEXT,
            entry_price REAL,
            exit_price REAL,
            amount REAL,
            profit REAL,
            status TEXT
        )
    ''')
    conn.commit()
    conn.close()

initialize_database()

# --- Fonctions DB ---
def get_trades(limit=50):
    conn = sqlite3.connect(DATABASE_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?', (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_last_trade():
    trades = get_trades(1)
    return trades[0] if trades else None

def save_trade(trade_type, price, amount, profit=0):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO trades (timestamp, type, symbol, entry_price, exit_price, amount, profit, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (datetime.now().isoformat(), trade_type, SYMBOL, price, price if trade_type == 'SELL' else 0, amount, profit, 'closed'))
    conn.commit()
    conn.close()

# --- Variables Globales pour le Dashboard ---
bot_running = False
current_price = 0.0
current_capital = 1000.0
bot_status = "Arrêté"

# --- LOGIQUE DU BOT (Le moteur) ---
async def run_bot_logic():
    global bot_running, current_price, bot_status, current_capital
    
    # Connexion à Binance
    exchange = ccxt.binance({'enableRateLimit': True})
    
    while bot_running:
        try:
            bot_status = "Analyse en cours..."
            # 1. Récupérer les bougies (OHLCV)
            bars = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=10)
            df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
            current_price = df['close'].iloc[-1]
            
            last_trade = get_last_trade()

            # CAS A : On a une position ouverte (on cherche à vendre)
            if last_trade and last_trade['type'] == 'BUY':
                entry_price = last_trade['entry_price']
                perf = (current_price - entry_price) / entry_price
                
                logger.info(f"EN POSITION: {perf*100:+.2f}% | Prix: {current_price}")

                if perf >= TAKE_PROFIT or perf <= -STOP_LOSS:
                    profit_usdt = (current_price - entry_price) * last_trade['amount']
                    save_trade('SELL', current_price, last_trade['amount'], profit_usdt)
                    current_capital += profit_usdt
                    logger.info(f">>> VENTE EFFECTUÉE: {profit_usdt:+.2f}$")
                
            # CAS B : Pas de position (on cherche à acheter)
            else:
                # Stratégie : 1 Rouge + 2 Vertes
                c1 = df.iloc[-4] # Il y a 3 min
                c2 = df.iloc[-3] # Il y a 2 min
                c3 = df.iloc[-2] # Il y a 1 min (fermée)
                
                is_c1_red = c1['close'] < c1['open']
                is_c2_green = c2['close'] > c2['open']
                is_c3_green = c3['close'] > c3['open']
                
                logger.info(f"SCAN: [{ 'R' if is_c1_red else 'V' }][{ 'V' if is_c2_green else 'R' }][{ 'V' if is_c3_green else 'R' }]")

                if is_c1_red and is_c2_green and is_c3_green:
                    amount = TRADE_AMOUNT_USDT / current_price
                    save_trade('BUY', current_price, amount)
                    logger.info(f">>> ACHAT EFFECTUÉ à {current_price}")

            bot_status = "Actif - Veille 1min"
            # Attente de 60 secondes (vérification chaque minute)
            for _ in range(60):
                if not bot_running: break
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Erreur boucle: {e}")
            await asyncio.sleep(10)
    
    await exchange.close()

# --- FastAPI Setup ---
app = FastAPI()
templates = Jinja2Templates(directory="templates")
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "current_price": current_price,
        "current_capital": current_capital,
        "bot_status": bot_status,
        "trades_history": get_trades(20)
    })

@app.post("/start")
async def start_bot():
    global bot_running
    if not bot_running:
        bot_running = True
        asyncio.create_task(run_bot_logic())
        return {"message": "Démarré"}
    return {"message": "Déjà en cours"}

@app.post("/stop")
async def stop_bot():
    global bot_running
    bot_running = False
    return {"message": "Arrêté"}

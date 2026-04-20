import asyncio
import sqlite3
import os
import ccxt.async_support as ccxt  # Changé pour avoir les bougies
import pandas as pd                # Pour analyser les bougies
import logging
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

# --- Configuration du Logger ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration des variables de base de données ---
DATABASE_NAME = "trading_bot.db"
TRADES_TABLE = "trades"

# --- CONFIGURATION STRATÉGIE ---
SYMBOL = "BTC/USDT"
TIMEFRAME = "1m"
TRADE_AMOUNT_USDT = 50 
TAKE_PROFIT = 0.002 # +0.2%
STOP_LOSS = 0.001   # -0.1%

# --- Fonctions de gestion de la base de données ---
def initialize_database():
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {TRADES_TABLE} (
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
    except Exception as e:
        logger.error(f"Erreur DB : {e}")

initialize_database()

def get_trades(limit=50):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(f'SELECT * FROM {TRADES_TABLE} ORDER BY timestamp DESC LIMIT ?', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except:
        return []

def add_trade(trade_data):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute(f'''
            INSERT INTO {TRADES_TABLE} (timestamp, type, symbol, entry_price, exit_price, amount, profit, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            trade_data.get('timestamp', datetime.now().isoformat()),
            trade_data.get('type', ''),
            trade_data.get('symbol', ''),
            trade_data.get('entry_price', 0.0),
            trade_data.get('exit_price', 0.0),
            trade_data.get('amount', 0.0),
            trade_data.get('profit', 0.0),
            trade_data.get('status', 'closed')
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Erreur ajout trade : {e}")

# --- Variables Globales ---
bot_running = False
bot_task = None
current_price = 0.0
current_capital = 1000.00
crypto_held = 0.0 
last_buy_price = 0.0 
bot_status = "Arrêté"
trade_history_memory = []

# --- Logique du Bot (MODIFIÉE POUR 1 ROUGE + 2 VERTES) ---
async def run_bot_logic():
    global bot_running, current_price, current_capital, bot_status, crypto_held, last_buy_price
    
    # Initialisation de l'échange
    exchange = ccxt.binance({'enableRateLimit': True})
    bot_status = "En cours d'exécution"
    
    try:
        while bot_running:
            try:
                # 1. Récupération des bougies (OHLCV)
                bars = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=10)
                df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                current_price = df['close'].iloc[-1]
                
                logger.info(f"[ANALYSE] {SYMBOL} : {current_price}$ | Portefeuille : {current_capital:.2f}$ / {crypto_held:.5f} BTC")

                # 2. LOGIQUE DE STRATÉGIE
                if crypto_held > 0:
                    # --- ON CHERCHE À VENDRE (TP/SL) ---
                    perf = (current_price - last_buy_price) / last_buy_price
                    if perf >= TAKE_PROFIT or perf <= -STOP_LOSS:
                        reason = "TAKE_PROFIT" if perf >= TAKE_PROFIT else "STOP_LOSS"
                        profit = (current_price - last_buy_price) * crypto_held
                        
                        trade_data = {
                            'type': 'SELL', 'symbol': SYMBOL, 'entry_price': last_buy_price,
                            'exit_price': current_price, 'amount': crypto_held, 'profit': profit, 'status': reason
                        }
                        add_trade(trade_data)
                        
                        current_capital = crypto_held * current_price
                        crypto_held = 0.0
                        logger.info(f">>> VENTE {reason} à {current_price}$ | Profit: {profit:.2f}$")

                else:
                    # --- ON CHERCHE À ACHETER (1 ROUGE + 2 VERTES) ---
                    # On vérifie les bougies précédentes fermées : -4, -3, -2
                    c1 = df.iloc[-4] # La plus ancienne
                    c2 = df.iloc[-3]
                    c3 = df.iloc[-2] # La plus récente fermée

                    is_red = c1['close'] < c1['open']
                    is_green1 = c2['close'] > c2['open']
                    is_green2 = c3['close'] > c3['open']

                    if is_red and is_green1 and is_green2:
                        if current_capital >= 10:
                            logger.info(">>> SIGNAL ACHAT DÉTECTÉ <<<")
                            amount_to_buy = TRADE_AMOUNT_USDT / current_price
                            
                            trade_data = {
                                'type': 'BUY', 'symbol': SYMBOL, 'entry_price': current_price,
                                'amount': amount_to_buy, 'status': 'open'
                            }
                            add_trade(trade_data)
                            
                            crypto_held = amount_to_buy
                            current_capital -= (amount_to_buy * current_price)
                            last_buy_price = current_price

                # Pause de 60 secondes pour le timeframe 1m
                for _ in range(60):
                    if not bot_running: break
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.error(f"Erreur boucle : {e}")
                await asyncio.sleep(10)
                    
    finally:
        await exchange.close()
        bot_status = "Arrêté"
        bot_running = False

def start_bot():
    global bot_running, bot_task
    bot_running = True
    bot_task = asyncio.create_task(run_bot_logic())

def stop_bot():
    global bot_running
    bot_running = False

# --- Application FastAPI ---
app = FastAPI()

templates = Jinja2Templates(directory="templates")
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_root(request: Request):
    context = {
        "request": request,
        "current_price": current_price,
        "current_capital": current_capital,
        "bot_status": bot_status,
        "trades_history": get_trades(limit=50)
    }
    # Correction ici : on ajoute request=request
    return templates.TemplateResponse(
        request=request, 
        name="index.html", 
        context=context
    )

@app.get("/stats")
async def api_stats():
    return {
        "current_price": current_price,
        "current_capital": current_capital,
        "bot_status": bot_status,
        "trades_history": get_trades(limit=10)
    }

@app.post("/start")
async def start_bot_api():
    global bot_running
    if not bot_running:
        start_bot()
        return {"message": "Démarré"}
    return {"message": "Déjà en cours"}

@app.post("/stop")
async def stop_bot_api():
    global bot_running
    bot_running = False
    return {"message": "Arrêté"}

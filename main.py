import asyncio
import sqlite3
import os
import ccxt.async_support as ccxt
import pandas as pd
import pandas_ta as ta  # <-- NOUVEL IMPORT POUR LES INDICATEURS
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

# --- CONFIGURATION STRATÉGIE (MISE À JOUR) ---
SYMBOL = "SOL/USDT"
TIMEFRAME = "15m"
TRADE_AMOUNT_USDT = 50 
TAKE_PROFIT = 0.01      # +1.0% (Objectif)
STOP_LOSS = 0.0075      # -0.75% (Sécurité)
TIME_OUT_CANDLES = 10   # Fermeture après 10 bougies si rien n'est touché

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
            datetime.now().isoformat(),
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
candles_held = 0  # <-- NOUVEAU : Pour compter le temps passé dans le trade

# --- Logique du Bot (KUCOIN + STRATÉGIE SOL 15M) ---
async def run_bot_logic():
    global bot_running, current_price, current_capital, bot_status, crypto_held, last_buy_price, candles_held
    
    exchange = ccxt.kucoin({'enableRateLimit': True})
    bot_status = "En cours d'exécution"
    
    # Variables pour détecter si on vient de passer à une nouvelle bougie
    last_candle_timestamp = None
    
    try:
        while bot_running:
            try:
                # 1. Récupération de 60 bougies (nécessaire pour calculer l'EMA 50)
                bars = await exchange.fetch_ohlcv(SYMBOL, timeframe=TIMEFRAME, limit=60)
                df = pd.DataFrame(bars, columns=['ts', 'open', 'high', 'low', 'close', 'vol'])
                
                # Calcul des indicateurs techniques
                df['EMA_50'] = ta.ema(df['close'], length=50)
                df['RSI_14'] = ta.rsi(df['close'], length=14)
                
                current_price = df['close'].iloc[-1] # Prix actuel en direct
                current_candle_ts = df['ts'].iloc[-1]
                
                # Si c'est une nouvelle bougie de 15m, on incrémente le compteur de temps du trade
                if last_candle_timestamp is not None and current_candle_ts != last_candle_timestamp:
                    if crypto_held > 0:
                        candles_held += 1
                last_candle_timestamp = current_candle_ts

                logger.info(f"[ANALYSE] {SYMBOL} : {current_price}$ | Capital : {current_capital:.2f}$")

                # 2. LOGIQUE DE STRATÉGIE
                if crypto_held > 0:
                    # GESTION DE LA VENTE (TP/SL/TIME-OUT)
                    perf = (current_price - last_buy_price) / last_buy_price
                    reason = None
                    
                    if perf >= TAKE_PROFIT:
                        reason = "TAKE_PROFIT"
                    elif perf <= -STOP_LOSS:
                        reason = "STOP_LOSS"
                    elif candles_held >= TIME_OUT_CANDLES:
                        reason = "TIME_OUT"
                        
                    if reason:
                        profit = (current_price - last_buy_price) * crypto_held
                        
                        trade_data = {
                            'type': 'SELL', 'symbol': SYMBOL, 'entry_price': last_buy_price,
                            'exit_price': current_price, 'amount': crypto_held, 'profit': profit, 'status': reason
                        }
                        add_trade(trade_data)
                        
                        current_capital += (crypto_held * current_price)
                        crypto_held = 0.0
                        candles_held = 0
                        logger.info(f">>> VENTE {reason} à {current_price}$ | Profit: {profit:.2f}$")

                else:
                    # GESTION DE L'ACHAT (Rebond en Tendance)
                    # On analyse les bougies CLÔTURÉES (iloc[-2] et iloc[-3]) pour éviter les faux signaux
                    precedente = df.iloc[-3]
                    actuelle = df.iloc[-2]
                    
                    # On s'assure que l'EMA 50 est calculée
                    if pd.notna(actuelle['EMA_50']):
                        # Conditions strictes de la stratégie
                        tendance_haussiere = actuelle['close'] > actuelle['EMA_50']
                        respiration = precedente['RSI_14'] < 45 or actuelle['RSI_14'] < 45
                        
                        bougie_rouge_avant = precedente['close'] < precedente['open']
                        bougie_verte_actuelle = actuelle['close'] > actuelle['open']
                        
                        milieu_rouge_precedente = (precedente['open'] + precedente['close']) / 2
                        force_acheteuse = actuelle['close'] > milieu_rouge_precedente

                        if tendance_haussiere and respiration and bougie_rouge_avant and bougie_verte_actuelle and force_acheteuse:
                            if current_capital >= TRADE_AMOUNT_USDT:
                                logger.info(">>> SIGNAL ACHAT DÉTECTÉ (Rebond SOL) <<<")
                                amount_to_buy = TRADE_AMOUNT_USDT / current_price
                                
                                trade_data = {
                                    'type': 'BUY', 'symbol': SYMBOL, 'entry_price': current_price,
                                    'amount': amount_to_buy, 'status': 'open'
                                }
                                add_trade(trade_data)
                                
                                crypto_held = amount_to_buy
                                current_capital -= TRADE_AMOUNT_USDT
                                last_buy_price = current_price
                                candles_held = 0

                # Attente (On vérifie le prix toutes les minutes pour déclencher le TP/SL au bon moment, 
                # même si les bougies sont en 15m)
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
    return templates.TemplateResponse(request=request, name="index.html", context=context)

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

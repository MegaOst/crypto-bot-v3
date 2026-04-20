import asyncio
import sqlite3
import os
import aiohttp
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

# --- Fonctions de gestion de la base de données ---
def initialize_database():
    """Crée la base de données et la table des trades si elles n'existent pas."""
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
        logger.info(f"Base de données '{DATABASE_NAME}' et table '{TRADES_TABLE}' prêtes.")
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation de la base de données : {e}")
        exit(1)

initialize_database()

def get_trades(limit=50):
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(f'''
            SELECT timestamp, type, symbol, entry_price, exit_price, amount, profit, status
            FROM {TRADES_TABLE}
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Erreur SQLite lors de la récupération des trades : {e}")
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
        logger.info(f"Nouveau trade ajouté en base : {trade_data['type']} à {trade_data.get('entry_price', trade_data.get('exit_price'))}$")
    except Exception as e:
        logger.error(f"Erreur lors de l'ajout du trade en base : {e}")

# --- Variables Globales ---
bot_running = False
bot_task = None
current_price = 0.0
current_capital = 1000.00
crypto_held = 0.0 # Ajout d'une variable pour savoir si on possède de la crypto
last_buy_price = 0.0 # Pour calculer le profit à la vente
bot_status = "Arrêté"
trade_history_memory = []

# --- Logique du Bot ---
async def run_bot_logic():
    global bot_running, current_price, current_capital, bot_status, crypto_held, last_buy_price
    bot_status = "En cours d'exécution"
    logger.info(f"Bot démarré. Vérification du marché...")
    
    try:
        while bot_running:
            try:
                # 1. Appel API CoinGecko
                url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
                async with aiohttp.ClientSession() as session:
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            current_price = data['bitcoin']['usd']
                            logger.info(f"[ANALYSE] Prix actuel du BTC : {current_price} $ | Capital : {current_capital:.2f} $ | Crypto possédée : {crypto_held:.5f} BTC")
                        else:
                            logger.error(f"Erreur API CoinGecko : HTTP {response.status}")
                
                # 2. ---> LOGIQUE DE STRATÉGIE DE TEST <---
                # Attention : Ceci est une stratégie fictive pour vérifier que l'enregistrement des trades fonctionne.
                if current_price > 0:
                    
                    # CONDITION D'ACHAT (Si on a tout en capital USD)
                    if current_capital >= 10: # On achète si on a au moins 10$
                        logger.info(">>> SIGNAL D'ACHAT DÉTECTÉ <<<")
                        amount_to_buy = current_capital / current_price
                        
                        trade_data = {
                            'timestamp': datetime.now().isoformat(),
                            'type': 'BUY',
                            'symbol': 'BTC/USD',
                            'entry_price': current_price,
                            'exit_price': 0.0,
                            'amount': amount_to_buy,
                            'profit': 0.0,
                            'status': 'open'
                        }
                        add_trade(trade_data)
                        
                        # Mise à jour du portefeuille
                        crypto_held = amount_to_buy
                        current_capital = 0.0
                        last_buy_price = current_price
                        logger.info(f"Achat effectué. Nouveau solde crypto : {crypto_held:.5f} BTC")
                        
                    # CONDITION DE VENTE (Si on possède de la crypto)
                    elif crypto_held > 0:
                        logger.info(">>> SIGNAL DE VENTE DÉTECTÉ <<<")
                        profit = (current_price - last_buy_price) * crypto_held
                        
                        trade_data = {
                            'timestamp': datetime.now().isoformat(),
                            'type': 'SELL',
                            'symbol': 'BTC/USD',
                            'entry_price': last_buy_price,
                            'exit_price': current_price,
                            'amount': crypto_held,
                            'profit': profit,
                            'status': 'closed'
                        }
                        add_trade(trade_data)
                        
                        # Mise à jour du portefeuille
                        current_capital = crypto_held * current_price
                        crypto_held = 0.0
                        logger.info(f"Vente effectuée. Profit : {profit:.2f} $. Nouveau capital : {current_capital:.2f} $")

                # Pause de 5 minutes (300 secondes) 
                # (Vous pouvez descendre à 30 secondes pour voir les trades plus vite si vous testez)
                logger.info("Attente de 5 minutes avant la prochaine analyse...")
                for _ in range(300):
                    if not bot_running:
                        break
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.error(f"Erreur dans la boucle du bot : {e}")
                for _ in range(60):
                    if not bot_running:
                        break
                    await asyncio.sleep(1)
                    
    except Exception as e:
        logger.error(f"Erreur critique du bot : {e}")
    finally:
        bot_status = "Arrêté"
        bot_running = False
        logger.info("La boucle du bot s'est arrêtée.")

def start_bot():
    global bot_running, bot_task
    bot_running = True
    loop = asyncio.get_event_loop()
    bot_task = loop.create_task(run_bot_logic())

def stop_bot():
    global bot_running
    bot_running = False

# --- Application FastAPI ---
app = FastAPI()

if not os.path.exists("templates"):
    os.makedirs("templates")
if not os.path.exists("static"):
    os.makedirs("static")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Routes Web ---
@app.get("/")
async def read_root(request: Request):
    try:
        db_trades = get_trades(limit=50)
        display_trades = list(db_trades)
        for mem_trade in trade_history_memory:
            if mem_trade not in display_trades and mem_trade.get('status') == 'open':
                display_trades.append(mem_trade)

        display_trades.sort(key=lambda x: str(x.get('timestamp', '0')), reverse=True)
        display_trades = display_trades[:50]
    except Exception as e:
        logger.error(f"Erreur chargement dashboard : {e}")
        display_trades = []

    context = {
        "request": request,
        "current_price": current_price,
        "current_capital": current_capital,
        "bot_status": bot_status,
        "trades_history": display_trades
    }

    try:
        return templates.TemplateResponse(request=request, name="index.html", context=context)
    except Exception as e:
        logger.error(f"Erreur rendu HTML : {e}")
        return {"error": "Erreur serveur"}

# --- Routes API ---
@app.get("/stats")
async def api_stats():
    return {
        "current_price": current_price,
        "current_capital": current_capital,
        "bot_status": bot_status,
        "trades_history": get_trades(limit=100)
    }

@app.post("/start")
async def start_bot_api():
    global bot_running
    if not bot_running:
        start_bot()
        return {"message": "Bot démarré avec succès."}
    else:
        raise HTTPException(status_code=400, detail="Le bot est déjà en cours d'exécution.")

@app.post("/stop")
async def stop_bot_api():
    global bot_running
    if bot_running:
        stop_bot()
        return {"message": "Bot arrêté avec succès."}
    else:
        raise HTTPException(status_code=400, detail="Le bot n'est pas en cours d'exécution.")

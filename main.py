import asyncio
import sqlite3
import os
import ccxt.async_support as ccxt
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
        exit(1) # On arrête le script si la DB ne peut pas s'initialiser

# INITIALISATION IMMEDIATE DE LA DB (Avant même de configurer FastAPI)
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
    except Exception as e:
        logger.error(f"Erreur lors de l'ajout du trade en base : {e}")

# --- Variables Globales ---
bot_running = False
bot_task = None
current_price = 0.0
current_capital = 1000.00
bot_status = "Arrêté"
trade_history_memory = []

# --- Logique du Bot (Exemple/Structure) ---
async def run_bot_logic():
    global bot_running, current_price, current_capital, bot_status
    bot_status = "En cours d'exécution"
    try:
        exchange = ccxt.binance()
        while bot_running:
            try:
                ticker = await exchange.fetch_ticker('BTC/USDT')
                current_price = ticker['last']
                # ---> Placez votre logique de stratégie de trading ici <---
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Erreur dans la boucle du bot : {e}")
                await asyncio.sleep(5)
        await exchange.close()
    except Exception as e:
        logger.error(f"Erreur critique du bot : {e}")
    finally:
        bot_status = "Arrêté"
        bot_running = False

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

# Configuration des dossiers (assure qu'ils existent pour éviter des crashs)
if not os.path.exists("templates"):
    os.makedirs("templates")
if not os.path.exists("static"):
    os.makedirs("static")

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Routes Web ---
@app.get("/")
async def read_root(request: Request):
    logger.info("Requête reçue pour la page d'accueil.")
    try:
        # Récupérer les trades depuis la DB
        db_trades = get_trades(limit=50)

        # Combiner avec la mémoire en cours
        display_trades = list(db_trades)
        for mem_trade in trade_history_memory:
            if mem_trade not in display_trades and mem_trade.get('status') == 'open':
                display_trades.append(mem_trade)

        # Trier par date décroissante
        display_trades.sort(key=lambda x: str(x.get('timestamp', '0')), reverse=True)
        display_trades = display_trades[:50]

    except Exception as e:
        logger.error(f"Erreur lors de la préparation des trades pour le dashboard : {e}", exc_info=True)
        display_trades = [{"error": "Erreur de chargement des trades"}]

    context = {
        "request": request,
        "current_price": current_price,
        "current_capital": current_capital,
        "bot_status": bot_status,
        "trades_history": display_trades
    }

    try:
        # CORRECTION DEFINITIVE : Utilisation des paramètres nommés (request=, name=, context=)
        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context=context
        )
    except Exception as e:
        logger.error(f"Erreur lors du rendu du template 'index.html' : {e}", exc_info=True)
        try:
            # CORRECTION DEFINITIVE POUR L'ERREUR AUSSI
            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context={"request": request, "error_message": "Erreur interne du serveur lors du chargement du tableau de bord."}
            )
        except Exception as render_error:
            logger.error(f"Impossible de rendre même le template d'erreur : {render_error}", exc_info=True)
            raise HTTPException(status_code=500, detail="Erreur serveur interne critique.")

# --- Routes API ---
@app.get("/stats")  # <-- ON RETIRE LE "/api" ICI
async def api_stats():
    return {
        "current_price": current_price,
        "current_capital": current_capital,
        "bot_status": bot_status,
        "trades_history": get_trades(limit=100)
    }

@app.post("/api/start_bot")
async def start_bot_api():
    global bot_running
    if not bot_running:
        start_bot()
        return {"message": "Bot démarré avec succès."}
    else:
        raise HTTPException(status_code=400, detail="Le bot est déjà en cours d'exécution.")

@app.post("/api/stop_bot")
async def stop_bot_api():
    global bot_running
    if bot_running:
        stop_bot()
        return {"message": "Bot arrêté avec succès."}
    else:
        raise HTTPException(status_code=400, detail="Le bot n'est pas en cours d'exécution.")

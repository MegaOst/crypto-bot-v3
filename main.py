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
    conn = None
    try:
        # Utiliser 'connect' crée le fichier DB s'il n'existe pas
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        # Création de la table avec des colonnes courantes pour les trades
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {TRADES_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL, -- 'buy' ou 'sell'
                symbol TEXT NOT NULL,
                entry_price REAL,
                exit_price REAL,
                amount REAL,
                profit REAL,
                status TEXT -- 'open', 'closed'
            )
        ''')
        conn.commit()
        logger.info(f"Base de données '{DATABASE_NAME}' et table '{TRADES_TABLE}' prêtes.")
    except sqlite3.Error as e:
        logger.error(f"Erreur SQLite lors de l'initialisation de la base de données : {e}", exc_info=True)
        # Il est crucial que la DB soit initialisée, donc on relance l'erreur pour arrêter le démarrage
        raise
    finally:
        if conn:
            conn.close()

# --- Appel à l'initialisation de la DB AVANT toute autre chose ---
# Ceci garantit que la DB est prête avant même que FastAPI ne démarre ses routes.
try:
    initialize_database()
except Exception as e:
    logger.critical(f"Échec critique de l'initialisation de la base de données. L'application ne peut pas démarrer. Erreur : {e}", exc_info=True)
    # Dans un environnement conteneurisé, une erreur ici empêchera le conteneur de démarrer correctement.
    # Vous pourriez vouloir un mécanisme pour que le processus parent (comme Docker/Railway) détecte cet échec.
    exit(1) # Terminer le processus si la DB ne peut être initialisée


# --- Importer les modules personnalisés ---
try:
    from core.market import get_current_price
except ImportError as e:
    logger.error(f"Erreur d'importation de core.market : {e}. Assurez-vous que le fichier existe et est accessible.")
    raise HTTPException(status_code=500, detail="Module de marché non trouvé.")

# --- Initialisation de l'application FastAPI ---
app = FastAPI()

# --- Montage des fichiers statiques (CSS, JS, images) ---
# Décommentez et adaptez si vous avez un dossier 'static'
# try:
#     app.mount("/static", StaticFiles(directory="static"), name="static")
# except Exception as e:
#     logger.warning(f"Impossible de monter le dossier 'static'. Assurez-vous qu'il existe. Erreur : {e}")

# --- Configuration du dossier TEMPLATES ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
try:
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
except Exception as e:
    logger.error(f"Erreur lors de l'initialisation des templates Jinja2 depuis '{TEMPLATES_DIR}'. Assurez-vous que le dossier existe et que les templates sont accessibles. Erreur : {e}")
    raise HTTPException(status_code=500, detail="Erreur de configuration des templates.")

# --- Variables Globales et État du Bot ---
current_price = 0.00
current_capital = 1000.00
bot_status = "Arrêté"
bot_running = False
trade_history_memory = []
bot_task = None

# --- Fonctions de gestion de la base de données (inchangées par rapport à avant) ---

def add_trade(trade_data):
    global trade_history_memory
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute(f'''
            INSERT INTO {TRADES_TABLE} (timestamp, type, symbol, entry_price, exit_price, amount, profit, status)
            VALUES (:timestamp, :type, :symbol, :entry_price, :exit_price, :amount, :profit, :status)
        ''', trade_data)
        conn.commit()
        logger.info(f"Trade ajouté : {trade_data.get('symbol')} - {trade_data.get('type')}")

        formatted_trade = {
            "timestamp": str(trade_data.get('timestamp')),
            "type": str(trade_data.get('type')),
            "symbol": str(trade_data.get('symbol')),
            "entry_price": float(trade_data.get('entry_price', 0.0)),
            "exit_price": float(trade_data.get('exit_price', 0.0)),
            "amount": float(trade_data.get('amount', 0.0)),
            "profit": float(trade_data.get('profit', 0.0)),
            "status": str(trade_data.get('status', 'unknown'))
        }
        trade_history_memory.append(formatted_trade)
        if len(trade_history_memory) > 100:
            trade_history_memory.pop(0)

    except sqlite3.Error as e:
        logger.error(f"Erreur SQLite lors de l'ajout du trade : {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Erreur lors de l'ajout du trade en mémoire : {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

def get_trades(limit=50):
    """Récupère les N derniers trades de la base de données."""
    conn = None
    trades = []
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        # C'est ici que l'erreur 'no such table' se produisait. Maintenant, la table devrait exister.
        cursor.execute(f'''
            SELECT timestamp, type, symbol, entry_price, exit_price, amount, profit, status
            FROM {TRADES_TABLE}
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()

        columns = [description[0] for description in cursor.description]
        for row in rows:
            trade_dict = dict(zip(columns, row))
            trades.append({
                "timestamp": str(trade_dict.get('timestamp')),
                "type": str(trade_dict.get('type', '')),
                "symbol": str(trade_dict.get('symbol', '')),
                "entry_price": float(trade_dict.get('entry_price', 0.0) or 0.0),
                "exit_price": float(trade_dict.get('exit_price', 0.0) or 0.0),
                "amount": float(trade_dict.get('amount', 0.0) or 0.0),
                "profit": float(trade_dict.get('profit', 0.0) or 0.0),
                "status": str(trade_dict.get('status', 'unknown'))
            })
    except sqlite3.Error as e:
        logger.error(f"Erreur SQLite lors de la récupération des trades : {e}", exc_info=True)
        return [{"error": "Erreur de chargement des trades depuis la base de données."}]
    finally:
        if conn:
            conn.close()
    return trades

# --- Fonctions du Bot (inchangées) ---
async def run_bot_logic():
    global current_price, current_capital, bot_running, bot_status
    global trade_history_memory

    while bot_running:
        try:
            price_data = await get_current_price("BTC/USDT")
            if price_data and 'last' in price_data:
                current_price = price_data['last']
                logger.info(f"Prix actuel BTC/USDT : {current_price}")
            else:
                logger.warning("Impossible de récupérer le prix actuel du marché.")

            if current_price > 60000 and current_capital > 100 and bot_status == "Actif":
                logger.info(f"Seuil de prix atteint ({current_price}). Tentative d'achat simulée.")
                buy_amount = 0.001
                if current_capital >= buy_amount * current_price:
                    new_trade = {
                        "timestamp": datetime.now().isoformat(),
                        "type": "buy",
                        "symbol": "BTC/USDT",
                        "entry_price": current_price,
                        "exit_price": None,
                        "amount": buy_amount,
                        "profit": 0.0,
                        "status": "open"
                    }
                    add_trade(new_trade)
                    current_capital -= buy_amount * current_price
                    logger.info(f"Achat simulé : {buy_amount} BTC à {current_price}. Capital restant : {current_capital:.2f}")
                else:
                    logger.warning("Capital insuffisant pour l'achat simulé.")

            open_buy_trade = next((t for t in trade_history_memory if t['status'] == 'open' and t['type'] == 'buy'), None)
            if open_buy_trade and current_price > open_buy_trade['entry_price'] * 1.05 and bot_status == "Actif":
                logger.info(f"Seuil de vente atteint pour le trade ouvert ({current_price}). Tentative de vente simulée.")
                profit = (current_price - open_buy_trade['entry_price']) * open_buy_trade['amount']
                current_capital += open_buy_trade['amount'] * current_price
                open_buy_trade['exit_price'] = current_price
                open_buy_trade['profit'] = profit
                open_buy_trade['status'] = 'closed'
                logger.info(f"Vente simulée : {open_buy_trade['amount']} BTC à {current_price}. Profit : {profit:.2f}. Capital total : {current_capital:.2f}")

            await asyncio.sleep(15)

        except ccxt.NetworkError as e:
            logger.error(f"Erreur réseau CCXT : {e}. Réessai dans 60 secondes.")
            await asyncio.sleep(60)
        except sqlite3.Error as e:
            logger.error(f"Erreur SQLite pendant l'exécution du bot : {e}", exc_info=True)
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Erreur inattendue dans la logique du bot : {e}", exc_info=True)
            await asyncio.sleep(30)

def start_bot():
    global bot_running, bot_task, bot_status
    if not bot_running:
        bot_running = True
        bot_status = "Actif"
        bot_task = asyncio.create_task(run_bot_logic())
        logger.info("Bot démarré.")
    else:
        logger.warning("Le bot est déjà en cours d'exécution.")

def stop_bot():
    global bot_running, bot_task, bot_status
    if bot_running:
        bot_running = False
        if bot_task:
            bot_task.cancel()
            bot_task = None
        bot_status = "Arrêté"
        logger.info("Bot arrêté.")
    else:
        logger.warning("Le bot n'est pas en cours d'exécution.")

# --- Routes de l'application (inchangées) ---

@app.get("/")
async def read_root(request: Request):
    global current_capital, bot_status, current_price, trade_history_memory

    logger.info("Requête reçue pour la page d'accueil.")

    safe_current_price = current_price if isinstance(current_price, (int, float, str)) else "N/A"
    safe_current_capital = current_capital if isinstance(current_capital, (int, float)) else 0.0
    safe_bot_status = bot_status if isinstance(bot_status, str) else "Inconnu"

    display_trades = []
    try:
        db_trades = get_trades(limit=50)
        display_trades.extend(db_trades)

        for mem_trade in trade_history_memory:
            if mem_trade not in display_trades and mem_trade.get('status') == 'open':
                display_trades.append(mem_trade)

        display_trades.sort(key=lambda x: x.get('timestamp', '0'), reverse=True)
        display_trades = display_trades[:50]

    except Exception as e:
        logger.error(f"Erreur lors de la récupération ou du formatage des trades pour le dashboard : {e}", exc_info=True)
        display_trades = [{"error": "Erreur de chargement des trades"}]

    context = {
        "request": request,
        "current_price": safe_current_price,
        "current_capital": safe_current_capital,
        "bot_status": safe_bot_status,
        "trades_history": display_trades
    }
    logger.debug(f"Contexte pour le dashboard : Prix={context['current_price']}, Capital={context['current_capital']}, Status={context['bot_status']}, Nb Trades={len(context['trades_history'])}")

    try:
        return templates.TemplateResponse("index.html", context)
    except Exception as e:
        logger.error(f"Erreur lors du rendu du template 'index.html' : {e}", exc_info=True)
        try:
            return templates.TemplateResponse("error.html", {"request": request, "error_message": "Erreur interne du serveur lors du chargement du tableau de bord."})
        except Exception as render_error:
            logger.error(f"Impossible de rendre même le template d'erreur : {render_error}", exc_info=True)
            return HTTPException(status_code=500, detail="Erreur serveur interne critique.")

@app.get("/api/stats")
async def api_stats():
    global current_capital, bot_status, current_price, trade_history_memory
    trades = get_trades(limit=100)
    for mem_trade in trade_history_memory:
        if mem_trade not in trades and mem_trade.get('status') == 'open':
            trades.append(mem_trade)
    trades.sort(key=lambda x: x.get('timestamp', '0'), reverse=True)
    trades = trades[:100]
    return {
        "current_price": current_price,
        "current_capital": current_capital,
        "bot_status": bot_status,
        "trades_history": trades
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

# Le bloc if __name__ == "__main__": est généralement utilisé pour le lancement local.
# Sur des plateformes comme Railway, le serveur est lancé par la plateforme.
# Assurez-vous que votre configuration de déploiement démarre ce script principal.

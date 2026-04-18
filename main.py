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

# --- Fonction utilitaire pour nettoyer les données pour Jinja2 ---
def make_hashable(data):
    """
    Convertit récursivement les dictionnaires et listes en types hashables
    adaptés à Jinja2. Les dictionnaires deviennent des dictionnaires avec
    chaînes de caractères comme clés et valeurs simples. Les listes sont
    converties en listes de valeurs simples.
    """
    if isinstance(data, dict):
        # Nettoyer chaque clé et valeur du dictionnaire
        return {str(k): make_hashable(v) for k, v in data.items()}
    elif isinstance(data, (list, tuple)):
        # Nettoyer chaque élément de la liste/tuple
        return [make_hashable(item) for item in data]
    elif data is None:
        return "" # Ou un autre valeur par défaut appropriée comme 0 ou "N/A"
    elif isinstance(data, (int, float, str, bool)):
        return data # Les types primitifs sont déjà hashables
    else:
        # Essayer de convertir d'autres types vers une chaîne de caractères
        # ou un autre type simple, et logger si cela semble suspect.
        try:
            return str(data)
        except Exception as e:
            logger.warning(f"Impossible de convertir l'élément {type(data)} en hashable : {e}. Remplacement par 'conversion_error'.")
            return "conversion_error"

# --- Fonctions de gestion de la base de données ---
def initialize_database():
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {TRADES_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                symbol TEXT NOT NULL,
                entry_price REAL,
                exit_price REAL,
                amount REAL,
                profit REAL,
                status TEXT
            )
        ''')
        conn.commit()
        logger.info(f"Base de données '{DATABASE_NAME}' et table '{TRADES_TABLE}' prêtes.")
    except sqlite3.Error as e:
        logger.error(f"Erreur SQLite lors de l'initialisation de la base de données : {e}", exc_info=True)
        raise
    finally:
        if conn:
            conn.close()

# --- Appel à l'initialisation de la DB AVANT toute autre chose ---
try:
    initialize_database()
except Exception as e:
    logger.critical(f"Échec critique de l'initialisation de la base de données. L'application ne peut pas démarrer. Erreur : {e}", exc_info=True)
    exit(1)

# --- Importer les modules personnalisés ---
try:
    from core.market import get_current_price
except ImportError as e:
    logger.error(f"Erreur d'importation de core.market : {e}.")
    raise HTTPException(status_code=500, detail="Module de marché non trouvé.")

# --- Initialisation de l'application FastAPI ---
app = FastAPI()

# --- Configuration du dossier TEMPLATES ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
try:
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
except Exception as e:
    logger.error(f"Erreur lors de l'initialisation des templates Jinja2 depuis '{TEMPLATES_DIR}'. Erreur : {e}")
    raise HTTPException(status_code=500, detail="Erreur de configuration des templates.")

# --- Variables Globales et État du Bot ---
current_price = 0.00
current_capital = 1000.00
bot_status = "Arrêté"
bot_running = False
trade_history_memory = []
bot_task = None

# --- Fonctions de gestion de la base de données ---
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

        # Créer un dictionnaire propre pour la mémoire
        formatted_trade = {
            "timestamp": str(trade_data.get('timestamp')),
            "type": str(trade_data.get('type')),
            "symbol": str(trade_data.get('symbol')),
            "entry_price": float(trade_data.get('entry_price', 0.0) or 0.0),
            "exit_price": float(trade_data.get('exit_price', 0.0) or 0.0),
            "amount": float(trade_data.get('amount', 0.0) or 0.0),
            "profit": float(trade_data.get('profit', 0.0) or 0.0),
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
    conn = None
    trades = []
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
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
            # Nettoyer chaque champ du dictionnaire avant de l'ajouter à la liste
            cleaned_trade = {
                "timestamp": str(trade_dict.get('timestamp')),
                "type": str(trade_dict.get('type', '')),
                "symbol": str(trade_dict.get('symbol', '')),
                "entry_price": float(trade_dict.get('entry_price', 0.0) or 0.0),
                "exit_price": float(trade_dict.get('exit_price', 0.0) or 0.0),
                "amount": float(trade_dict.get('amount', 0.0) or 0.0),
                "profit": float(trade_dict.get('profit', 0.0) or 0.0),
                "status": str(trade_dict.get('status', 'unknown'))
            }
            trades.append(cleaned_trade)
    except sqlite3.Error as e:
        logger.error(f"Erreur SQLite lors de la récupération des trades : {e}", exc_info=True)
        # Retourner une liste d'erreur propre pour Jinja2
        return [{"error": "Erreur de chargement des trades depuis la base de données."}]
    finally:
        if conn:
            conn.close()
    return trades

# --- Fonctions du Bot ---
async def run_bot_logic():
    global current_price, current_capital, bot_running, bot_status
    global trade_history_memory

    while bot_running:
        try:
            # Récupération du prix
            price_data = await get_current_price("BTC/USDT")
            if price_data and 'last' in price_data:
                current_price = price_data['last']
                logger.info(f"Prix actuel BTC/USDT : {current_price}")
            else:
                logger.warning("Impossible de récupérer le prix actuel du marché.")
                current_price = "N/A" # S'assurer que current_price est toujours un type simple en cas d'erreur

            # Logique d'achat simulé
            if isinstance(current_price, (int, float)) and current_price > 60000 and current_capital > 100 and bot_status == "Actif":
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

            # Logique de vente simulé
            open_buy_trade = next((t for t in trade_history_memory if t['status'] == 'open' and t['type'] == 'buy'), None)
            if open_buy_trade and isinstance(current_price, (int, float)) and current_price > open_buy_trade['entry_price'] * 1.05 and bot_status == "Actif":
                logger.info(f"Seuil de vente atteint pour le trade ouvert ({current_price}). Tentative de vente simulée.")
                profit = (current_price - open_buy_trade['entry_price']) * open_buy_trade['amount']
                current_capital += open_buy_trade['amount'] * current_price
                open_buy_trade['exit_price'] = current_price
                open_buy_trade['profit'] = profit
                open_buy_trade['status'] = 'closed'
                logger.info(f"Vente simulée : {open_buy_trade['amount']} BTC à {current_price}. Profit : {profit:.2f}. Capital total : {current_capital:.2f}")

            await asyncio.sleep(15) # Intervalle de vérification

        except ccxt.NetworkError as e:
            logger.error(f"Erreur réseau CCXT : {e}. Réessai dans 60 secondes.")
            current_price = "Network Error" # S'assurer que current_price est un type simple
            await asyncio.sleep(60)
        except sqlite3.Error as e:
            logger.error(f"Erreur SQLite pendant l'exécution du bot : {e}", exc_info=True)
            current_price = "DB Error"
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Erreur inattendue dans la logique du bot : {e}", exc_info=True)
            current_price = "Bot Error"
            await asyncio.sleep(30)

def start_bot():
    global bot_running, bot_task, bot_status
    if not bot_running:
        bot_running = True
        bot_status = "Actif"
        # Assurer que le prix est initialisé correctement avant de lancer le bot
        # Si le premier appel échoue, on essaie de le définir à une valeur sûre.
        if not isinstance(current_price, (int, float)):
            current_price = 0.00
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

# --- Routes de l'application ---

@app.get("/")
async def read_root(request: Request):
    logger.info("Requête reçue pour la page d'accueil.")

    # Préparer les données à passer au template, en s'assurant qu'elles sont hashables
    try:
        # Récupérer les trades depuis la DB et la mémoire
        db_trades = get_trades(limit=50) # get_trades retourne déjà des données propres

        # Combiner et nettoyer les trades de la mémoire
        display_trades = list(db_trades) # Copie des trades de la DB
        for mem_trade in trade_history_memory:
            # On ajoute seulement si le trade n'est pas déjà présent (ou s'il est ouvert et DB n'a que closed)
            if mem_trade not in display_trades and mem_trade.get('status') == 'open':
                display_trades.append(mem_trade)

        display_trades.sort(key=lambda x: x.get('timestamp', '0'), reverse=True)
        display_trades = display_trades[:50] # Limiter à 50 trades

        # Nettoyer explicitement la liste de trades pour être sûr
        cleaned_trades_history = make_hashable(display_trades)

    except Exception as e:
        logger.error(f"Erreur lors de la préparation des trades pour le dashboard : {e}", exc_info=True)
        cleaned_trades_history = [{"error": "Erreur de chargement des trades"}] # S'assurer que c'est un format hashable


    # Nettoyer les autres variables pour le contexte
    safe_current_price = make_hashable(current_price)
    safe_current_capital = make_hashable(current_capital)
    safe_bot_status = make_hashable(bot_status)

    # Construire le contexte final avec des données garanties hashables
    context = {
        "request": request,
        "current_price": safe_current_price,
        "current_capital": safe_current_capital,
        "bot_status": safe_bot_status,
        "trades_history": cleaned_trades_history
    }

    # Logger le contexte AVANT le rendu pour débogage
    # Utiliser repr() pour une représentation plus sûre des dicts/lists complexes si besoin
    # logger.debug(f"Contexte pour le dashboard : {context}")

    try:
        # Tenter de rendre le template principal
        return templates.TemplateResponse("index.html", context)
    except Exception as e:
        logger.error(f"Erreur lors du rendu du template 'index.html' : {e}", exc_info=True)
        # Si le rendu échoue, tenter de rendre le template d'erreur
        try:
            # Le contexte pour error.html est simple et ne devrait pas poser de problème
            return templates.TemplateResponse("error.html", {"request": request, "error_message": "Erreur interne du serveur lors du chargement du tableau de bord."})
        except Exception as render_error:
            logger.error(f"Impossible de rendre même le template d'erreur : {render_error}", exc_info=True)
            return HTTPException(status_code=500, detail="Erreur serveur interne critique.")

@app.get("/api/stats")
async def api_stats():
    """API endpoint pour obtenir les statistiques actuelles."""
    global current_capital, bot_status, current_price, trade_history_memory

    # Récupérer les trades les plus récents
    trades = get_trades(limit=100)
    # Ajouter les trades de mémoire qui sont ouverts et non persistés
    for mem_trade in trade_history_memory:
        if mem_trade not in trades and mem_trade.get('status') == 'open':
            trades.append(mem_trade)
    trades.sort(key=lambda x: x.get('timestamp', '0'), reverse=True)
    trades = trades[:100] # Limiter à 100 pour l'API

    # Assurer que les données retournées sont dans des formats simples
    return {
        "current_price": make_hashable(current_price),
        "current_capital": make_hashable(current_capital),
        "bot_status": make_hashable(bot_status),
        "trades_history": make_hashable(trades) # Nettoyer aussi les trades pour l'API
    }

@app.post("/api/start_bot")
async def start_bot_api():
    """API endpoint pour démarrer le bot."""
    global bot_running
    if not bot_running:
        start_bot()
        return {"message": "Bot démarré avec succès."}
    else:
        raise HTTPException(status_code=400, detail="Le bot est déjà en cours d'exécution.")

@app.post("/api/stop_bot")
async def stop_bot_api():
    """API endpoint pour arrêter le bot."""
    global bot_running
    if bot_running:
        stop_bot()
        return {"message": "Bot arrêté avec succès."}
    else:
        raise HTTPException(status_code=400, detail="Le bot n'est pas en cours d'exécution.")

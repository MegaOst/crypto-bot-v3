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

# --- Importer les modules personnalisés ---
try:
    # Assurez-vous que core/market.py existe et contient get_current_price
    from core.market import get_current_price
except ImportError as e:
    logger.error(f"Erreur d'importation de core.market : {e}. Assurez-vous que le fichier existe et est accessible.")
    # On lance une erreur fatale si le marché n'est pas dispo
    raise HTTPException(status_code=500, detail="Module de marché non trouvé.")

# --- Initialisation de l'application FastAPI ---
app = FastAPI()

# --- Montage des fichiers statiques (CSS, JS, images) ---
# Décommentez si vous avez un dossier 'static'
# app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Configuration du dossier TEMPLATES ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- Variables Globales ---
current_price = 0.00
current_capital = 1000.00  # Capital de départ par défaut
bot_status = "Arrêté"
bot_running = False
trade_history_memory = [] # Stockage en mémoire des trades pour un accès rapide

# --- Fonctions de gestion de la base de données ---

def initialize_database():
    """Crée la base de données et la table des trades si elles n'existent pas."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {TRADES_TABLE} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                amount REAL NOT NULL,
                price REAL NOT NULL,
                profit REAL DEFAULT 0.0
            )
        ''')
        conn.commit()
        logger.info(f"Base de données '{DATABASE_NAME}' et table '{TRADES_TABLE}' prêtes.")
    except sqlite3.Error as e:
        logger.error(f"Erreur SQLite lors de l'initialisation de la base de données : {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

def add_trade(trade_data):
    """Ajoute une transaction à la base de données."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute(f'''
            INSERT INTO {TRADES_TABLE} (timestamp, type, amount, price, profit)
            VALUES (?, ?, ?, ?, ?)
        ''', (trade_data['timestamp'], trade_data['type'], trade_data['amount'], trade_data['price'], trade_data.get('profit', 0.0)))
        conn.commit()
        logger.info(f"Trade ajouté en base de données : {trade_data}")
        # Mettre à jour l'historique en mémoire si on le souhaite
        trade_history_memory.append(trade_data)
        # Limiter la taille de l'historique en mémoire
        if len(trade_history_memory) > 50:
            trade_history_memory.pop(0) # Supprime le plus ancien
    except sqlite3.Error as e:
        logger.error(f"Erreur SQLite lors de l'ajout d'un trade : {e}", exc_info=True)
    finally:
        if conn:
            conn.close()

def get_trades(limit=10):
    """Récupère les N dernières transactions de la base de données."""
    conn = None
    trades = []
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        cursor.execute(f'SELECT timestamp, type, amount, price, profit FROM {TRADES_TABLE} ORDER BY timestamp DESC LIMIT ?', (limit,))
        rows = cursor.fetchall()
        # Convertir les tuples en dictionnaires pour une meilleure lisibilité
        for row in rows:
            trades.append({
                "timestamp": row[0],
                "type": row[1],
                "amount": row[2],
                "price": row[3],
                "profit": row[4]
            })
        logger.debug(f"{len(trades)} trades récupérés de la base de données.")
    except sqlite3.Error as e:
        logger.error(f"Erreur SQLite lors de la récupération des trades : {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
    return trades

# --- Fonctions Utilitaires du Bot ---

async def fetch_market_data():
    """Fonction pour récupérer le prix actuel du marché."""
    global current_price, bot_running
    if not bot_running:
        return

    try:
        # Utilise la fonction importée de core.market
        price_data = await get_current_price("BTC/USDT") # Exemple avec BTC/USDT
        if price_data and "last" in price_data: # Ajustez la clé selon le retour de get_current_price
            current_price = price_data["last"]
            logger.info(f"Prix actuel récupéré : {current_price}")
        else:
            logger.warning("Données de prix invalides reçues du marché.")
            current_price = "N/A"

    except Exception as e:
        logger.error(f"Erreur lors de la récupération des données du marché : {e}", exc_info=True)
        current_price = "Erreur"

async def run_bot_logic():
    """Logique principale du bot."""
    global bot_running, current_capital, trade_history_memory
    while bot_running:
        await fetch_market_data() # Met à jour le prix du marché

        # --- IMPLÉMENTEZ VOTRE STRATÉGIE DE TRADING ICI ---
        # Exemple :
        if current_price != "N/A" and current_price != "Erreur":
            try:
                # Convertir le prix en float pour les comparaisons
                float_price = float(current_price)

                # Exemple de stratégie simple: acheter si le prix baisse de 5% par rapport à un point de référence
                # Ou simplement logguer l'état
                # logger.info(f"Bot en cours : Prix={current_price}, Capital={current_capital}")

                # Si vous voulez simuler un trade et le sauvegarder:
                # trade_timestamp = datetime.now().isoformat()
                # simulated_trade = {
                #     "timestamp": trade_timestamp,
                #     "type": "buy", # ou "sell"
                #     "amount": 0.001,
                #     "price": float_price,
                #     "profit": 0.0 # Calculez le profit si c'est une vente
                # }
                # add_trade(simulated_trade) # Sauvegarde en base de données et met à jour trade_history_memory

            except ValueError:
                logger.warning(f"Impossible de convertir le prix '{current_price}' en nombre pour la stratégie.")
            except Exception as e:
                logger.error(f"Erreur dans la logique du bot : {e}", exc_info=True)

        # --- FIN DE LA STRATÉGIE ---

        await asyncio.sleep(10) # Attendre 10 secondes avant la prochaine itération

# --- Routes de l'application ---

@app.get("/")
async def read_root(request: Request):
    """Route principale pour afficher le dashboard."""
    global current_capital, bot_status, current_price

    logger.info("Requête reçue pour la page d'accueil.")

    # Assurer que les variables sont des types simples pour Jinja2
    safe_current_price = current_price if isinstance(current_price, (int, float, str)) else "N/A"
    safe_current_capital = current_capital if isinstance(current_capital, (int, float)) else 0.0
    safe_bot_status = bot_status if isinstance(bot_status, str) else "Inconnu"

    # Récupérer les trades depuis la base de données et l'historique en mémoire
    try:
        # On combine les trades récents de la DB avec ceux en mémoire pour avoir un affichage plus complet
        # On prend les 20 derniers de la DB et on ajoute ceux en mémoire (si pas déjà dedans)
        db_trades = get_trades(limit=20)
        combined_trades = db_trades + [t for t in trade_history_memory if t not in db_trades]
        # S'assurer qu'il n'y a pas de doublons et trier par timestamp si nécessaire
        # Ici, on affiche les 50 derniers trades combinés
        display_trades = combined_trades[-50:]

    except Exception as e:
        logger.error(f"Erreur lors de la récupération des trades pour le dashboard : {e}", exc_info=True)
        display_trades = [{"error": "Erreur de chargement des trades"}]

    context = {
        "request": request,
        "current_price": safe_current_price,
        "current_capital": safe_current_capital,
        "bot_status": safe_bot_status,
        "trades_history": display_trades # Passer l'historique des trades
    }
    logger.debug(f"Contexte pour le dashboard : Prix={context['current_price']}, Capital={context['current_capital']}, Status={context['bot_status']}, Nb Trades={len(context['trades_history'])}")

    try:
        return templates.TemplateResponse("index.html", context)
    except Exception as e:
        logger.error(f"Erreur lors du rendu du template 'index.html': {e}", exc_info=True)
        # Renvoyer une réponse d'erreur générique si le rendu échoue
        try:
            return templates.TemplateResponse("error.html", {"request": request, "error_message": "Erreur interne du serveur lors du chargement du tableau de bord."})
        except Exception as render_error:
            logger.error(f"Impossible de rendre même le template d'erreur : {render_error}", exc_info=True)
            return HTTPException(status_code=500, detail="Erreur serveur interne critique.")


@app.get("/api/stats")
async def get_stats():
    """Renvoie les données actuelles au format JSON."""
    global current_price, current_capital, bot_status

    # Assurer que les données sont dans un format JSON-compatible
    safe_current_price = current_price if isinstance(current_price, (int, float, str)) else "N/A"
    safe_current_capital = current_capital if isinstance(current_capital, (int, float)) else 0.0
    safe_bot_status = bot_status if isinstance(bot_status, str) else "Inconnu"

    # Récupérer les derniers trades de la base de données
    try:
        # On récupère les 10 derniers trades de la DB
        recent_db_trades = get_trades(limit=10)
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des trades pour l'API: {e}", exc_info=True)
        recent_db_trades = [{"error": "Erreur de chargement des trades"}]

    return {
        "price": safe_current_price,
        "capital": safe_current_capital,
        "status": safe_bot_status,
        "trades": recent_db_trades
    }

@app.post("/api/start_bot")
async def start_bot_api():
    """API endpoint pour démarrer le bot."""
    global bot_running, bot_status
    if not bot_running:
        bot_running = True
        bot_status = "En cours"
        asyncio.create_task(run_bot_logic()) # Lance la tâche en arrière-plan
        logger.info("Bot démarré via API.")
        return {"message": "Bot démarré avec succès."}
    else:
        return {"message": "Le bot est déjà en cours d'exécution."}

@app.post("/api/stop_bot")
async def stop_bot_api():
    """API endpoint pour arrêter le bot."""
    global bot_running, bot_status
    if bot_running:
        bot_running = False
        bot_status = "Arrêté"
        logger.info("Bot arrêté via API.")
        return {"message": "Bot arrêté avec succès."}
    else:
        return {"message": "Le bot est déjà arrêté."}

# --- Initialisation au démarrage ---
# On initialise la DB ici, juste avant que FastAPI ne démarre l'application
initialize_database()

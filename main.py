import asyncio
import sqlite3
import os
import ccxt.async_support as ccxt
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
import logging

# --- Configuration du Logging ---
# Utilise un format plus détaillé pour les logs
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__) # Nom du logger

app = FastAPI()

# --- Configuration du Dossier Templates ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- Variables Globales (dans un dictionnaire pour une meilleure gestion) ---
bot_state = {
    "current_price": 0.00,
    "current_capital": 1000.00,
    "status": "Arrêté",
    "running": False,
    "has_position": False,
    "buy_price": 0.0,
    "exchange": None, # Instance de l'échange CCXT
    "last_error": None # Pour stocker le dernier message d'erreur
}

# --- Base de Données SQLite ---
DB_PATH = os.path.join(BASE_DIR, 'trading_bot.db')

def init_db():
    """Initialise la base de données et crée la table des trades si elle n'existe pas."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT, 
                action TEXT, 
                price REAL, 
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                profit_loss REAL DEFAULT 0.0
            )
        ''')
        conn.commit()
        logger.info("Base de données initialisée avec succès.")
    except Exception as e:
        logger.error(f"Erreur lors de l'initialisation de la base de données : {e}")
    finally:
        if conn:
            conn.close()

def log_trade(action, price, profit_loss=0.0):
    """Enregistre un trade dans la base de données."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO trades (action, price, profit_loss) VALUES (?, ?, ?)", (action, price, profit_loss))
        conn.commit()
        logger.info(f"Trade enregistré : {action} à {price:.2f} $ (P/L: {profit_loss:.2f} $)")
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement du trade : {e}")
    finally:
        if conn:
            conn.close()

def get_recent_trades():
    """Récupère les 50 derniers trades pour le dashboard."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT action, price, timestamp, profit_loss FROM trades ORDER BY timestamp DESC LIMIT 50")
        trades = [{"action": row[0], "price": row[1], "date": row[2], "profit_loss": row[3]} for row in c.fetchall()]
        return trades
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des trades : {e}")
        return []
    finally:
        if conn:
            conn.close()

# --- Fonctions d'initialisation et d'arrêt du Bot ---

async def initialize_exchange():
    """Tente d'initialiser l'échange CCXT."""
    if bot_state["exchange"] is None:
        try:
            # Pourrais ajouter des clés API ici si nécessaire (ex: api_key='YOUR_API_KEY', secret='YOUR_SECRET')
            # Binance a des limites pour les appels sans clé API
            bot_state["exchange"] = ccxt.binance({
                'enableRateLimit': True, # Gère les limites de taux de l'API
            })
            # Test rapide pour vérifier la connexion (optionnel)
            await bot_state["exchange"].fetch_time() 
            logger.info("Échange CCXT (Binance) initialisé avec succès.")
            bot_state["last_error"] = None # Efface les erreurs précédentes
            return True
        except ccxt.NetworkError as e:
            error_msg = f"Erreur réseau lors de l'initialisation de Binance : {type(e).__name__} - {e}"
            logger.error(error_msg)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur connexion échange"
        except ccxt.ExchangeError as e:
            error_msg = f"Erreur d'échange lors de l'initialisation de Binance : {type(e).__name__} - {e}"
            logger.error(error_msg)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur échange"
        except Exception as e:
            error_msg = f"Erreur inconnue lors de l'initialisation de Binance : {type(e).__name__} - {e}"
            logger.error(error_msg)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur inconnue"
    return False

async def close_exchange():
    """Ferme proprement la connexion CCXT."""
    if bot_state["exchange"]:
        try:
            await bot_state["exchange"].close()
            logger.info("Connexion CCXT fermée.")
            bot_state["exchange"] = None
        except Exception as e:
            logger.error(f"Erreur lors de la fermeture de la connexion CCXT : {e}")

# --- Logique Principale du Bot ---
async def run_bot_logic():
    """Boucle principale d'exécution du bot."""
    global bot_state

    if not await initialize_exchange():
        logger.error("Impossible de démarrer le bot car l'échange n'a pas pu être initialisé.")
        bot_state["status"] = "Erreur init échange"
        bot_state["running"] = False
        return

    logger.info(f"Moteur démarré avec un capital de {bot_state['current_capital']:.2f} $")
    bot_state["status"] = "Actif"

    while bot_state["running"]:
        try:
            # 1. Récupération du prix
            ticker = await bot_state["exchange"].fetch_ticker('BTC/USDT')
            bot_state["current_price"] = ticker['last']
            bot_state["status"] = "Actif" # Assure que le statut est bien "Actif"
            bot_state["last_error"] = None # Efface les erreurs précédentes si la requête réussit

            logger.debug(f"Prix BTC/USDT actuel : {bot_state['current_price']:.2f} $")

            # ==========================================
            # 2. STRATÉGIE (Simulation d'achats/ventes)
            # ==========================================
            if not bot_state["has_position"]:
                # Simulation d'un signal d'achat
                logger.info(f"🚀 Signal d'ACHAT détecté ! Achat à {bot_state['current_price']:.2f} $")
                bot_state["buy_price"] = bot_state["current_price"]
                bot_state["has_position"] = True
                log_trade("ACHAT", bot_state["current_price"])
                
            elif bot_state["has_position"] and bot_state["current_price"] > bot_state["buy_price"] * 1.01:
                # Simulation de vente si +1% de profit
                profit = bot_state["current_price"] - bot_state["buy_price"]
                bot_state["current_capital"] += profit
                log_trade("VENTE", bot_state["current_price"], profit)
                logger.info(f"📉 Signal de VENTE détecté ! Vente à {bot_state['current_price']:.2f} $ | Profit: {profit:.2f} $")
                bot_state["has_position"] = False
                bot_state["buy_price"] = 0.0
                bot_state["current_capital"] = round(bot_state["current_capital"], 2) # Arrondir le capital

            # ==========================================

        except ccxt.NetworkError as e:
            error_msg = f"Erreur réseau CCXT : {type(e).__name__} - {e}"
            logger.error(error_msg)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur réseau"
            # Tenter de réinitialiser l'échange en cas d'erreur réseau
            await close_exchange() 
            await asyncio.sleep(5) # Petite pause avant de réessayer l'initialisation
            if not await initialize_exchange(): # Tente de réinitialiser
                logger.error("Échec de la réinitialisation de l'échange après erreur réseau.")
                # Si ça échoue à nouveau, on peut décider d'arrêter le bot
                # bot_state["running"] = False # Décommenter si vous voulez que le bot s'arrête complètement
        except ccxt.ExchangeError as e:
            error_msg = f"Erreur d'échange CCXT : {type(e).__name__} - {e}"
            logger.error(error_msg)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur échange"
            # Peut-être tenter une réinitialisation aussi ici, ou juste attendre
            await asyncio.sleep(5)
        except Exception as e:
            error_msg = f"Erreur inconnue dans la boucle du bot : {type(e).__name__} - {e}"
            logger.error(error_msg)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur inconnue"
            await asyncio.sleep(5)
            
        # Attend avant la prochaine itération si le bot tourne
        if bot_state["running"]:
            await asyncio.sleep(5) 

    # Le bot s'arrête ici
    logger.info("Moteur du bot arrêté.")
    bot_state["status"] = "Arrêté"
    await close_exchange() # Fermeture propre à la fin de la boucle

# --- Tâche de Fond pour le Bot ---
bot_task = None # Variable pour garder une référence à la tâche du bot

@app.on_event("startup")
async def startup_event():
    """Démarre la tâche asynchrone du bot au lancement de l'application."""
    global bot_task
    # Assure qu'une seule instance de la tâche tourne
    if bot_task is None or bot_task.done():
        logger.info("Démarrage de la tâche du bot...")
        bot_state["running"] = True # Marque le bot comme prêt à tourner
        bot_task = asyncio.create_task(run_bot_logic())
        logger.info("Tâche du bot créée et lancée.")
    else:
        logger.warning("La tâche du bot est déjà en cours d'exécution.")

@app.on_event("shutdown")
async def shutdown_event():
    """Arrête proprement le bot et la tâche asynchrone lors de l'arrêt de l'application."""
    global bot_task, bot_state
    logger.info("Arrêt de l'application demandé. Arrêt du bot...")
    
    bot_state["running"] = False # Indique à la boucle du bot de s'arrêter
    
    if bot_task:
        try:
            logger.info("Attente de la fin de la tâche du bot (max 10 secondes)...")
            # Attend que la tâche se termine ou qu'elle soit annulée
            await asyncio.wait_for(bot_task, timeout=10.0) 
            logger.info("Tâche du bot terminée proprement.")
        except asyncio.TimeoutError:
            logger.warning("Timeout atteint en attendant la fin de la tâche du bot. Annulation...")
            bot_task.cancel() # Annule la tâche si elle ne se termine pas
            # Attend un peu que l'annulation soit effective
            try:
                await bot_task 
            except asyncio.CancelledError:
                logger.info("Tâche du bot annulée.")
        except Exception as e:
            logger.error(f"Erreur lors de l'attente de la tâche du bot : {e}")
            
    await close_exchange() # S'assure que la connexion CCXT est fermée
    logger.info("Arrêt de l'application terminé.")

# --- Routes de l'Interface Web ---
@app.get("/")
async def home(request: Request):
    """Rend la page d'accueil (index.html)."""
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/stats")
async def stats():
    """Renvoie les statistiques actuelles du bot et l'historique des trades."""
    return {
        "price": bot_state["current_price"],
        "capital": bot_state["current_capital"],
        "status": bot_state["status"],
        "trades": get_recent_trades(),
        "last_error": bot_state["last_error"] if bot_state["last_error"] else "" # Transmet le dernier message d'erreur au frontend
    }

@app.post("/start")
async def start_bot_route():
    """Démarre le processus du bot."""
    global bot_state, bot_task
    if not bot_state["running"]:
        logger.info("Route /start : Démarrage du bot...")
        bot_state["running"] = True
        bot_state["status"] = "Démarrage..." 
        bot_state["last_error"] = None # Efface les anciennes erreurs

        # Redémarre la tâche si elle a été arrêtée ou n'existe pas
        if bot_task is None or bot_task.done():
            bot_task = asyncio.create_task(run_bot_logic())
        # Si la tâche existe déjà mais n'est pas marquée comme running, on la relance
        elif not bot_state["running"]: # Ce cas ne devrait pas arriver si bot_task est déjà fait, mais par sécurité
            bot_state["running"] = True
        else:
            logger.warn("Route /start : La tâche du bot est déjà en cours et marquée comme running.")
            
        return {"message": "Tentative de démarrage du bot..."}
    else:
        logger.warning("Route /start : Le bot est déjà actif.")
        return {"message": "Le bot est déjà en cours d'exécution."}

@app.post("/stop")
async def stop_bot_route():
    """Arrête le processus du bot."""
    global bot_state
    if bot_state["running"]:
        logger.info("Route /stop : Arrêt du bot demandé...")
        bot_state["running"] = False # Indique à la boucle de s'arrêter
        # La fonction shutdown_event s'occupera de la fermeture propre
        return {"message": "Arrêt du bot demandé. Il s'arrêtera lors de la prochaine vérification."}
    else:
        logger.warning("Route /stop : Le bot est déjà arrêté.")
        return {"message": "Le bot est déjà arrêté."}

# --- Exécution locale (pour tester) ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Démarrage de l'application en mode local avec Uvicorn...")
    # Le mode reload=True est utile pour le développement local, mais à désactiver sur Railway
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=False) 

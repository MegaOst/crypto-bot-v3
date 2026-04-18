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
logging.basicConfig(level=logging.DEBUG, format=LOG_FORMAT)# Niveau INFO par défaut, DEBUG pour plus de détails
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
        logger.info(f"Tentative d'initialisation de la base de données à : {DB_PATH}")
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Log avant la création de table pour voir si on arrive jusque là
        logger.debug("Exécution de la requête CREATE TABLE IF NOT EXISTS trades...")
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
        logger.info("Base de données initialisée avec succès et table 'trades' prête.")
    except Exception as e:
        # Log d'erreur plus détaillé ici
        logger.error(f"Erreur critique lors de l'initialisation de la base de données : {e.__class__.__name__} - {e}", exc_info=True)
        # Si l'erreur est "no such table", c'est probablement que la création a échoué précédemment
        # et que le bot essaie d'insérer des données avant que la table soit créée.
    finally:
        if conn:
            conn.close()
            logger.debug("Connexion à la base de données fermée après initialisation.")

def log_trade(action, price, profit_loss=0.0):
    """Enregistre un trade dans la base de données."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        logger.debug(f"Tentative d'insertion du trade : {action}, {price}, {profit_loss}")
        c.execute("INSERT INTO trades (action, price, profit_loss) VALUES (?, ?, ?)", (action, price, profit_loss))
        conn.commit()
        logger.info(f"Trade enregistré : {action} à {price:.2f} $ (P/L: {profit_loss:.2f} $)")
    except sqlite3.OperationalError as e:
        # Capture spécifiquement l'erreur de table inexistante
        logger.error(f"Erreur opérationnelle lors de l'enregistrement du trade : {e.__class__.__name__} - {e}. La table 'trades' existe-t-elle ?")
        # Ici, on pourrait déclencher une réinitialisation de la DB ou une alerte plus forte
        if "no such table: trades" in str(e):
             logger.error("URGENCE : La table 'trades' n'existe pas ! Tentative de réinitialisation DB...")
             init_db() # Tente de recréer la table
             # On pourrait aussi relancer l'insertion après la réinitialisation si nécessaire
    except Exception as e:
        logger.error(f"Erreur lors de l'enregistrement du trade : {e.__class__.__name__} - {e}", exc_info=True)
    finally:
        if conn:
            conn.close()
            logger.debug("Connexion à la base de données fermée après log_trade.")

def get_recent_trades():
    """Récupère les 50 derniers trades pour le dashboard."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        logger.debug("Exécution de la requête SELECT pour les trades récents.")
        c.execute("SELECT action, price, timestamp, profit_loss FROM trades ORDER BY timestamp DESC LIMIT 50")
        trades = [{"action": row[0], "price": row[1], "date": row[2], "profit_loss": row[3]} for row in c.fetchall()]
        logger.info(f"{len(trades)} trades récupérés pour le dashboard.")
        return trades
    except sqlite3.OperationalError as e:
         logger.error(f"Erreur opérationnelle lors de la récupération des trades : {e.__class__.__name__} - {e}. La table 'trades' existe-t-elle ?")
         if "no such table: trades" in str(e):
             logger.error("URGENCE : La table 'trades' n'existe pas lors de la récupération ! Tentative de réinitialisation DB...")
             init_db() # Tente de recréer la table
         return []
    except Exception as e:
        logger.error(f"Erreur lors de la récupération des trades : {e.__class__.__name__} - {e}", exc_info=True)
        return []
    finally:
        if conn:
            conn.close()
            logger.debug("Connexion à la base de données fermée après get_recent_trades.")

# --- Fonctions d'initialisation et d'arrêt du Bot ---

async def initialize_exchange():
    """Tente d'initialiser l'échange CCXT avec des logs détaillés."""
    logger.info("Tentative d'initialisation de l'échange CCXT (Binance)...")
    if bot_state["exchange"] is None:
        try:
            # Ajout des clés API ici si nécessaire. Pour l'instant, on utilise l'accès public.
            # Les clés API ne sont pas requises pour fetch_ticker, mais sont nécessaires pour les opérations de trading.
            # Si vous déployez sur Railway, chargez vos clés API via les variables d'environnement.
            bot_state["exchange"] = ccxt.binance({
                'enableRateLimit': True, # Gère les limites de taux de l'API
                # Exemple avec clés API (décommenter si besoin) :
                # 'apiKey': os.environ.get('BINANCE_API_KEY', ''),
                # 'secret': os.environ.get('BINANCE_SECRET_KEY', ''),
                # 'options': {'defaultType': 'spot'}, # Spécifier le type de marché si nécessaire
            })
            logger.debug("Instance CCXT créée.")

            # Test rapide pour vérifier la connexion et l'authentification (si clés fournies)
            logger.debug("Vérification de l'heure du serveur...")
            exchange_time = await bot_state["exchange"].fetch_time()
            logger.info(f"Connexion à Binance réussie. Heure du serveur : {exchange_time}")

            # Essayer de charger les marchés, ce qui peut échouer en cas de problème d'API/clés
            logger.debug("Chargement des marchés...")
            await bot_state["exchange"].load_markets()
            logger.info("Échange CCXT (Binance) initialisé avec succès et marchés chargés.")
            bot_state["last_error"] = None # Efface les erreurs précédentes
            bot_state["status"] = "Initialisé" # Statut intermédiaire
            return True

        except ccxt.AuthenticationError as e:
            error_msg = f"Erreur d'authentification CCXT : {type(e).__name__} - {e}. Vérifiez vos clés API."
            logger.error(error_msg, exc_info=True)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur authentification"
        except ccxt.NetworkError as e:
            error_msg = f"Erreur réseau CCXT lors de l'initialisation : {type(e).__name__} - {e}"
            logger.error(error_msg, exc_info=True)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur connexion échange"
        except ccxt.ExchangeError as e:
            error_msg = f"Erreur d'échange CCXT lors de l'initialisation : {type(e).__name__} - {e}"
            logger.error(error_msg, exc_info=True)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur échange"
        except Exception as e:
            # Log détaillé pour toute autre exception
            error_msg = f"Erreur inconnue lors de l'initialisation de l'échange CCXT : {type(e).__name__} - {e}"
            logger.error(error_msg, exc_info=True)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur inconnue init"

    else:
        logger.warning("L'échange CCXT est déjà initialisé.")
        bot_state["status"] = "Actif" # S'assurer que le statut est correct
        return True # L'échange est déjà là

    logger.error("Échec de l'initialisation de l'échange CCXT.")
    return False

async def close_exchange():
    """Ferme proprement la connexion CCXT."""
    if bot_state["exchange"]:
        logger.info("Tentative de fermeture de la connexion CCXT...")
        try:
            await bot_state["exchange"].close()
            logger.info("Connexion CCXT fermée avec succès.")
            bot_state["exchange"] = None
        except Exception as e:
            logger.error(f"Erreur lors de la fermeture de la connexion CCXT : {type(e).__name__} - {e}", exc_info=True)
    else:
        logger.debug("Aucune connexion CCXT à fermer.")

# --- Logique Principale du Bot ---
async def run_bot_logic():
    """Boucle principale d'exécution du bot avec logs pour le debugging."""
    global bot_state

    # 1. Initialisation de la base de données au démarrage du bot
    init_db()

    # 2. Initialisation de l'échange CCXT
    if not await initialize_exchange():
        logger.error("Impossible de démarrer le bot car l'échange n'a pas pu être initialisé.")
        # Le statut est déjà mis à jour dans initialize_exchange()
        bot_state["running"] = False # Assure que la boucle while ne démarre pas
        return

    logger.info(f"Moteur démarré avec un capital de {bot_state['current_capital']:.2f} $")
    bot_state["status"] = "Actif" # Le bot est prêt à fonctionner

    while bot_state["running"]:
        try:
            # --- Récupération du prix ---
            logger.debug("Tentative de récupération du ticker BTC/USDT...")
            ticker = await bot_state["exchange"].fetch_ticker('BTC/USDT')
            current_price = ticker['last']
            bot_state["current_price"] = current_price
            bot_state["status"] = "Actif" # S'assurer que le statut reste "Actif"
            bot_state["last_error"] = None # Efface les erreurs précédentes si la requête réussit
            logger.info(f"Prix BTC/USDT actuel : {bot_state['current_price']:.2f} $") # Log INFO pour le prix

            # ==========================================
            # 2. STRATÉGIE (Simulation d'achats/ventes)
            # ==========================================
            if not bot_state["has_position"]:
                # Simulation d'un signal d'achat
                logger.info(f"🚀 Signal d'ACHAT détecté ! Préparation achat à {bot_state['current_price']:.2f} $")
                bot_state["buy_price"] = bot_state["current_price"]
                bot_state["has_position"] = True
                log_trade("ACHAT", bot_state["current_price"]) # Log le trade en base de données
                
            elif bot_state["has_position"] and bot_state["current_price"] > bot_state["buy_price"] * 1.01:
                # Simulation de vente si +1% de profit
                profit = bot_state["current_price"] - bot_state["buy_price"]
                bot_state["current_capital"] += profit
                log_trade("VENTE", bot_state["current_price"], profit) # Log le trade en base de données
                logger.info(f"📉 Signal de VENTE détecté ! Vente à {bot_state['current_price']:.2f} $ | Profit: {profit:.2f} $")
                bot_state["has_position"] = False
                bot_state["buy_price"] = 0.0
                bot_state["current_capital"] = round(bot_state["current_capital"], 2) # Arrondir le capital

            # ==========================================

        except ccxt.NetworkError as e:
            error_msg = f"Erreur réseau CCXT : {type(e).__name__} - {e}"
            logger.error(error_msg, exc_info=True)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur réseau"
            await close_exchange() # Fermer la connexion actuelle
            await asyncio.sleep(5) # Petite pause avant de réessayer l'initialisation
            if not await initialize_exchange(): # Tente de réinitialiser
                logger.error("Échec de la réinitialisation de l'échange après erreur réseau.")
                # Si ça échoue à nouveau, on peut décider d'arrêter le bot
                # bot_state["running"] = False # Décommenter si vous voulez que le bot s'arrête complètement
        except ccxt.ExchangeError as e:
            error_msg = f"Erreur d'échange CCXT : {type(e).__name__} - {e}"
            logger.error(error_msg, exc_info=True)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur échange"
            await asyncio.sleep(5) # Pause avant de continuer
        except Exception as e:
            error_msg = f"Erreur inconnue dans la boucle du bot : {type(e).__name__} - {e}"
            logger.error(error_msg, exc_info=True)
            bot_state["last_error"] = error_msg
            bot_state["status"] = "Erreur inconnue"
            await asyncio.sleep(5) # Pause avant de continuer
            
        # Attend avant la prochaine itération si le bot tourne
        if bot_state["running"]:
            await asyncio.sleep(5) # Intervalle entre chaque vérification de prix

    # Le bot s'arrête ici proprement
    logger.info("Moteur du bot arrêté (boucle 'while bot_state[\"running\"]' terminée).")
    bot_state["status"] = "Arrêté"
    await close_exchange() # S'assurer que la connexion CCXT est fermée

# --- Tâche de Fond pour le Bot ---
bot_task = None # Variable pour garder une référence à la tâche du bot

@app.on_event("startup")
async def startup_event():
    """Démarre la tâche asynchrone du bot au lancement de l'application."""
    global bot_task
    # Assure qu'une seule instance de la tâche tourne
    if bot_task is None or bot_task.done():
        logger.info("Démarrage de la tâche asynchrone du bot...")
        bot_state["running"] = True # Marque le bot comme prêt à tourner
        bot_task = asyncio.create_task(run_bot_logic())
        logger.info("Tâche du bot créée et lancée via asyncio.create_task.")
    else:
        logger.warning("La tâche du bot est déjà en cours d'exécution.")

@app.on_event("shutdown")
async def shutdown_event():
    """Arrête proprement le bot et la tâche asynchrone lors de l'arrêt de l'application."""
    global bot_task, bot_state
    logger.info("Arrêt de l'application demandé. Signal d'arrêt envoyé au bot...")
    
    bot_state["running"] = False # Indique à la boucle du bot de s'arrêter
    
    if bot_task:
        try:
            logger.info("Attente de la fin de la tâche du bot (max 10 secondes)...")
            # Attend que la tâche se termine naturellement ou qu'elle soit annulée
            await asyncio.wait_for(bot_task, timeout=10.0) 
            logger.info("Tâche du bot terminée proprement.")
        except asyncio.TimeoutError:
            logger.warning("Timeout atteint en attendant la fin de la tâche du bot. Annulation...")
            bot_task.cancel() # Annule la tâche si elle ne se termine pas
            # Attend un peu que l'annulation soit effective
            try:
                await bot_task 
            except asyncio.CancelledError:
                logger.info("Tâche du bot annulée avec succès.")
        except Exception as e:
            logger.error(f"Erreur lors de la gestion de la tâche du bot pendant l'arrêt : {type(e).__name__} - {e}", exc_info=True)
            
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
        logger.info("Route /start : Démarrage du bot demandé...")
        bot_state["running"] = True
        bot_state["status"] = "Démarrage..." 
        bot_state["last_error"] = None # Efface les anciennes erreurs

        # Redémarre la tâche si elle n'existe pas ou est terminée
        if bot_task is None or bot_task.done():
            logger.info("Création d'une nouvelle tâche pour run_bot_logic.")
            bot_task = asyncio.create_task(run_bot_logic())
        else:
            # Si la tâche existe déjà et est en cours, on s'assure juste qu'elle est marquée comme running
            logger.warning("Route /start : La tâche du bot est déjà en cours. Assure que 'running' est True.")
            bot_state["running"] = True # Au cas où elle aurait été désactivée entre temps
            
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
        # La fonction shutdown_event gérera la fermeture propre lors de l'arrêt de l'app
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

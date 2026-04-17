import asyncio
import sqlite3
import os
import ccxt.async_support as ccxt
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
import logging

# Configuration du logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

# --- CONFIGURATION DU DOSSIER TEMPLATES (Chemin absolu 100% fiable) ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- VARIABLES GLOBALES ---
# Utilisation d'un dictionnaire pour une meilleure gestion et éviter les "global" à répétition
bot_state = {
    "current_price": 0.00,
    "current_capital": 1000.00,  # Capital de départ par défaut
    "status": "Arrêté",
    "running": False,
    "has_position": False,
    "buy_price": 0.0,
    "exchange": None # Pour stocker l'instance de l'échange
}

# --- BASE DE DONNÉES SQLITE ---
DB_PATH = os.path.join(BASE_DIR, 'trading_bot.db')

def init_db():
    """Initialise la base de données et crée la table des trades si elle n'existe pas."""
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
        logging.info("Base de données initialisée avec succès.")
    except Exception as e:
        logging.error(f"Erreur lors de l'initialisation de la base de données : {e}")
    finally:
        if conn:
            conn.close()

def log_trade(action, price, profit_loss=0.0):
    """Enregistre un trade dans la base de données."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO trades (action, price, profit_loss) VALUES (?, ?, ?)", (action, price, profit_loss))
        conn.commit()
        conn.close()
        logging.info(f"Trade enregistré : {action} à {price:.2f} $ (P/L: {profit_loss:.2f} $)")
    except Exception as e:
        logging.error(f"Erreur lors de l'enregistrement du trade : {e}")

def get_recent_trades():
    """Récupère les 50 derniers trades pour le dashboard."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Ajout de la colonne profit_loss dans la requête
        c.execute("SELECT action, price, timestamp, profit_loss FROM trades ORDER BY timestamp DESC LIMIT 50")
        trades = [{"action": row[0], "price": row[1], "date": row[2], "profit_loss": row[3]} for row in c.fetchall()]
        conn.close()
        return trades
    except Exception as e:
        logging.error(f"Erreur lors de la récupération des trades : {e}")
        return []

# --- INITIALISATION ---
init_db()

# --- LOGIQUE DU BOT EN ARRIÈRE-PLAN ---
async def run_bot_logic():
    """Contient la boucle principale d'exécution du bot."""
    global bot_state # Accès à toutes les variables globales

    # Initialisation de l'échange si ce n'est pas déjà fait
    if bot_state["exchange"] is None:
        try:
            bot_state["exchange"] = ccxt.binance()
            logging.info("Moteur CCXT initialisé.")
        except Exception as e:
            logging.error(f"Erreur lors de l'initialisation de l'échange CCXT : {e}")
            bot_state["status"] = "Erreur échange"
            bot_state["running"] = False
            return

    logging.info(f"Moteur démarré avec un capital de {bot_state['current_capital']:.2f} $")
    bot_state["status"] = "Actif"

    while bot_state["running"]:
        try:
            # 1. Récupération du prix
            ticker = await bot_state["exchange"].fetch_ticker('BTC/USDT')
            bot_state["current_price"] = ticker['last']
            logging.debug(f"Prix BTC/USDT actuel : {bot_state['current_price']:.2f} $")

            # ==========================================
            # 2. STRATÉGIE (Simulation d'achats/ventes)
            # ==========================================
            if not bot_state["has_position"]:
                # Simulation d'un signal d'achat (ici, on achète dès que le bot est actif et sans position)
                logging.info(f"🚀 Signal d'ACHAT détecté ! Achat à {bot_state['current_price']:.2f} $")
                bot_state["buy_price"] = bot_state["current_price"]
                bot_state["has_position"] = True
                log_trade("ACHAT", bot_state["current_price"])
                
            elif bot_state["has_position"] and bot_state["current_price"] > bot_state["buy_price"] * 1.01: # Simulation de vente si +1% de profit
                profit = bot_state["current_price"] - bot_state["buy_price"]
                bot_state["current_capital"] += profit
                log_trade("VENTE", bot_state["current_price"], profit) # Enregistre le profit/perte
                logging.info(f"📉 Signal de VENTE détecté ! Vente à {bot_state['current_price']:.2f} $ | Profit: {profit:.2f} $")
                bot_state["has_position"] = False
                bot_state["buy_price"] = 0.0 # Réinitialise le prix d'achat
                # On peut aussi vouloir que le capital mis à jour soit visible immédiatement
                # bot_state["current_capital"] = round(bot_state["current_capital"], 2)

            # ==========================================
            # Mettre à jour le statut si le bot tourne
            bot_state["status"] = "Actif"

        except ccxt.NetworkError as e:
            logging.error(f"Erreur réseau CCXT : {e}. Tentative de reconnexion...")
            bot_state["status"] = "Erreur réseau"
            await asyncio.sleep(10) # Attente plus longue en cas d'erreur réseau
        except ccxt.ExchangeError as e:
            logging.error(f"Erreur d'échange CCXT : {e}")
            bot_state["status"] = "Erreur échange"
            await asyncio.sleep(10)
        except Exception as e:
            logging.error(f"Erreur inconnue dans la boucle du bot : {e}")
            bot_state["status"] = "Erreur inconnue"
            # Si une erreur critique survient, on peut décider d'arrêter le bot
            # bot_state["running"] = False
            await asyncio.sleep(5)
            
        # Attend avant la prochaine itération si le bot tourne
        if bot_state["running"]:
            await asyncio.sleep(5) # Intervalle de mise à jour du bot

    # Le bot s'arrête ici
    logging.info("Moteur du bot arrêté.")
    bot_state["status"] = "Arrêté"
    # Fermeture propre de la connexion CCXT
    if bot_state["exchange"]:
        await bot_state["exchange"].close()
        bot_state["exchange"] = None
        logging.info("Connexion CCXT fermée.")

# --- TÂCHE DE FOND POUR LE BOT ---
bot_task = None # Variable pour garder une référence à la tâche du bot

@app.on_event("startup")
async def startup_event():
    """Démarre la tâche asynchrone du bot au lancement de l'application."""
    global bot_task
    # Créer la tâche seulement si elle n'existe pas déjà (évite les doublons au redémarrage)
    if bot_task is None or bot_task.done():
        bot_task = asyncio.create_task(run_bot_logic())
        logging.info("Tâche du bot créée et démarrée.")

@app.on_event("shutdown")
async def shutdown_event():
    """Arrête proprement le bot et la tâche asynchrone lors de l'arrêt de l'application."""
    global bot_task, bot_state
    logging.info("Arrêt de l'application demandé...")
    
    # Marque le bot comme non exécuté
    bot_state["running"] = False
    
    # Attend que la tâche du bot se termine (avec un timeout)
    if bot_task:
        try:
            await asyncio.wait_for(bot_task, timeout=10.0) # Attend 10 secondes max
            logging.info("Tâche du bot terminée proprement.")
        except asyncio.TimeoutError:
            logging.warning("Timeout atteint en attendant la fin de la tâche du bot. Forçage de l'arrêt.")
            bot_task.cancel() # Annule la tâche si elle ne se termine pas
        except Exception as e:
            logging.error(f"Erreur lors de l'attente de la tâche du bot : {e}")
            
    # Fermeture de la connexion CCXT si elle est encore ouverte
    if bot_state["exchange"]:
        await bot_state["exchange"].close()
        bot_state["exchange"] = None
        logging.info("Connexion CCXT fermée lors de l'arrêt.")

# --- ROUTES DE L'INTERFACE WEB ---
@app.get("/")
async def home(request: Request):
    """Rend la page d'accueil (index.html)."""
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/stats")
async def stats():
    """Renvoie les statistiques actuelles du bot et l'historique des trades."""
    # Renvoie les statistiques ET l'historique des trades au dashboard
    return {
        "price": bot_state["current_price"],
        "capital": bot_state["current_capital"],
        "status": bot_state["status"],
        "trades": get_recent_trades()
    }

@app.post("/start")
async def start_bot_route():
    """Démarre le processus du bot."""
    global bot_state, bot_task
    if not bot_state["running"]:
        logging.info("Route /start : Démarrage du bot...")
        bot_state["running"] = True
        bot_state["status"] = "Démarrage..." # Indique qu'on est en train de démarrer
        # Recréer la tâche si elle n'existe pas ou si elle est terminée
        if bot_task is None or bot_task.done():
            bot_task = asyncio.create_task(run_bot_logic())
        else: # Si la tâche tourne déjà, on ne fait rien
            logging.warning("Route /start : Le bot est déjà en cours d'exécution.")
        return {"message": "Bot démarré"}
    else:
        logging.warning("Route /start : Le bot est déjà actif.")
        return {"message": "Le bot est déjà en cours d'exécution."}

@app.post("/stop")
async def stop_bot_route():
    """Arrête le processus du bot."""
    global bot_state
    if bot_state["running"]:
        logging.info("Route /stop : Arrêt du bot demandé...")
        bot_state["running"] = False
        # La tâche attendra d'elle-même son arrêt dans la boucle 'while bot_state["running"]:'
        return {"message": "Arrêt du bot demandé. Il s'arrêtera bientôt."}
    else:
        logging.warning("Route /stop : Le bot est déjà arrêté.")
        return {"message": "Le bot est déjà arrêté."}

# Pour exécuter localement (pas nécessaire sur Railway mais utile pour le test)
if __name__ == "__main__":
    import uvicorn
    # Lance l'application FastAPI avec Uvicorn
    # workers=1 pour éviter les problèmes avec les tâches asynchrones partagées
    uvicorn.run(app, host="0.0.0.0", port=8000)

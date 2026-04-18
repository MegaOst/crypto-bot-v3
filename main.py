import asyncio
import sqlite3
import os
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
import logging
from datetime import datetime

# --- Configuration du Logging ---
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# --- Configuration du Dossier Templates ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- Initialisation de l'Application FastAPI ---
app = FastAPI()

# --- Importation des Modules Locaux ---
try:
    # Assurez-vous que core est un package Python valide (contient __init__.py)
    from core.engine import PaperTradingEngine # Si utilisé
    from core.market import market_fetcher # Assurez-vous que market_fetcher est une instance dans market.py
except ImportError as e:
    logger.error(f"Erreur d'importation : {e}. Vérifiez la structure des dossiers et les fichiers.")
    # Dans un contexte de déploiement, une erreur d'importation ici peut empêcher le démarrage.

# --- Variables Globales et État du Bot ---
bot_runtime_state = {
    "running": False,
    "status": "Arrêté",
    "current_price": 0.00,
    "buy_price": 0.00,
    "has_position": False,
    "current_capital": 1000.00,
    "initial_capital": 1000.00,
    "last_error": None,
    "exchange": None,
    "trade_history": [], # Pour stocker les trades en mémoire si nécessaire, mais la BDD est la source principale
    "entry_time_log": None, # Pour stocker le temps d'entrée du trade en cours
    "last_entry_price": None # Pour stocker le prix d'entrée du trade en cours
}

# --- Base de Données SQLite ---
DB_NAME = "trading_bot.db"

def init_db():
    """Initialise la base de données SQLite et crée la table 'trades' si elle n'existe pas."""
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT NOT NULL,
                type TEXT NOT NULL, -- 'ACHAT' ou 'VENTE'
                price REAL NOT NULL,
                amount REAL, -- Montant acheté ou calculé
                entry_price REAL, -- Prix d'entrée si type='VENTE'
                exit_price REAL, -- Prix de sortie si type='VENTE'
                profit_pct REAL, -- Pourcentage de profit si type='VENTE'
                entry_time TEXT, -- Timestamp de l'entrée
                exit_time TEXT, -- Timestamp de la sortie
                reason TEXT -- Raison de la vente (e.g., 'TAKE_PROFIT', 'STOP_LOSS')
            )
        """)
        conn.commit()
        logger.info("Base de données 'trading_bot.db' initialisée et table 'trades' prête.")
    except sqlite3.Error as e:
        logger.error(f"Erreur lors de l'initialisation de la base de données : {e}")
    finally:
        if conn:
            conn.close()

def log_trade(trade_type, price, profit_pct=None, entry_price=None, reason="SIGNAL"):
    """
    Enregistre un trade dans la base de données SQLite et met à jour l'état du bot.
    """
    current_time_str = datetime.now().isoformat()
    asset = "BTC/USDT" # Symbole fixe pour l'instant
    conn = None # Initialiser conn à None

    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        entry_time_db = bot_runtime_state.get("entry_time_log", current_time_str) # Temps d'entrée enregistré

        if trade_type == "ACHAT":
            # On enregistre le prix d'achat et le temps pour pouvoir calculer le profit à la vente
            bot_runtime_state["last_entry_price"] = price
            bot_runtime_state["entry_time_log"] = current_time_str
            
            # Pour le moment, on ne logue pas directement l'achat dans la BDD,
            # car on ne connaît pas le montant exact sans un calcul plus poussé du capital.
            # On le loguera lors de la vente en utilisant le prix d'entrée.
            # Si vous voulez loguer tous les ordres, il faut adapter le schéma et la logique.
            logger.info(f"✅ Préparation ACHAT {asset} à {price:.2f} $ (prix d'entrée enregistré).")
            
        elif trade_type == "VENTE":
            entry_price_used = bot_runtime_state.get("last_entry_price")
            if entry_price_used is None:
                logger.error("Erreur critique : prix d'entrée manquant pour loguer une vente.")
                return # Ne pas loguer si le prix d'entrée est inconnu

            # Calcul du profit en dollar basé sur le prix d'entrée enregistré et le prix de vente actuel
            profit_usd = 0.0
            if entry_price_used and price:
                profit_usd = ((price - entry_price_used) / entry_price_used) * 100
            
            # Utilisation du profit_pct passé en argument s'il est pertinent, sinon calculé
            final_profit_pct = profit_pct if profit_pct is not None else profit_usd
            
            cursor.execute("""
                INSERT INTO trades (asset, type, price, entry_price, exit_price, profit_pct, entry_time, exit_time, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (asset, trade_type, price, entry_price_used, price, final_profit_pct, entry_time_db, current_time_str, reason))
            
            icon = "🔴" if final_profit_pct < 0 else "🔵"
            logger.info(f"{icon} Log VENTE {asset} à {price:.2f} $ | Raison: {reason} | P&L: {final_profit_pct:.2f}%")
            
            # --- Mise à jour du capital en mémoire ---
            # Le capital actuel est ajusté par le profit/perte réalisé
            capital_adjustment = bot_runtime_state["current_capital"] * (final_profit_pct / 100.0)
            bot_runtime_state["current_capital"] += capital_adjustment
            bot_runtime_state["current_capital"] = round(bot_runtime_state["current_capital"], 2)
            logger.info(f"Capital mis à jour: {bot_runtime_state['current_capital']:.2f} $")

            # Réinitialiser le prix d'entrée et le temps après une vente
            bot_runtime_state["last_entry_price"] = None
            bot_runtime_state["entry_time_log"] = None

        conn.commit()
        
    except sqlite3.Error as e:
        logger.error(f"Erreur lors de l'enregistrement du trade : {e}")
    finally:
        if conn:
            conn.close()


def get_bot_state():
    """Retourne l'état actuel du bot pour l'API, en s'assurant que les valeurs sont sérialisables."""
    return {
        "running": bot_runtime_state["running"],
        "status": bot_runtime_state["status"],
        "current_price": f"{bot_runtime_state['current_price']:.2f}" if bot_runtime_state['current_price'] else "N/A",
        "buy_price": f"{bot_runtime_state['buy_price']:.2f}" if bot_runtime_state["has_position"] and bot_runtime_state['buy_price'] else "N/A",
        "has_position": bot_runtime_state["has_position"],
        "current_capital": f"{bot_runtime_state['current_capital']:.2f}",
        "initial_capital": f"{bot_runtime_state['initial_capital']:.2f}",
        "last_error": bot_runtime_state["last_error"],
    }

# --- Logique Principale du Bot ---
async def run_bot_logic():
    """Boucle principale d'exécution du bot."""
    global bot_runtime_state

    logger.info("Démarrage de la boucle logique du bot...")
    bot_runtime_state["status"] = "Actif"
    bot_runtime_state["running"] = True
    # S'assurer que le capital initial est bien défini lors du démarrage
    if bot_runtime_state["current_capital"] == 0.0: # Si le capital a été remis à zéro
         bot_runtime_state["current_capital"] = bot_runtime_state["initial_capital"]
    logger.info(f"Moteur démarré avec un capital de {bot_runtime_state['current_capital']:.2f} $ (simulation paper trading)")

    while bot_runtime_state["running"]:
        try:
            # --- 1. Récupération du prix ---
            logger.debug("Tentative de récupération du prix BTC/USDT via CoinGecko...")
            current_price = market_fetcher.get_current_price("BTC/USDT") 

            if current_price is None or current_price == 0:
                logger.error("Impossible de récupérer le prix via CoinGecko (ou prix invalide).")
                bot_runtime_state["status"] = "Erreur Prix CoinGecko"
                bot_runtime_state["last_error"] = "Prix CoinGecko invalide ou non récupéré."
                await asyncio.sleep(10) 
                continue

            bot_runtime_state["current_price"] = current_price
            bot_runtime_state["status"] = "Actif"
            bot_runtime_state["last_error"] = None
            logger.info(f"Prix BTC/USDT actuel : {bot_runtime_state['current_price']:.2f} $")

            # ==========================================
            # 2. STRATÉGIE DE TRADING (Simulation)
            # ==========================================
            
            if not bot_runtime_state["has_position"]:
                # --- Condition d'ACHAT ---
                # Simulation: on achète dès que le prix est disponible et qu'on n'a pas de position
                # Remplacez ceci par votre logique de décision d'achat réelle
                
                # Exemple : on achète si le prix est inférieur à une moyenne mobile, ou si un signal est donné
                # Pour la simulation, on achète au premier prix obtenu s'il n'y a pas encore de prix d'entrée enregistré.
                if bot_runtime_state["last_entry_price"] is None: # Si pas de trade en cours
                    bot_runtime_state["buy_price"] = bot_runtime_state["current_price"] # Stocke le prix d'achat pour la logique de TP/SL
                    log_trade("ACHAT", bot_runtime_state["current_price"]) # Log l'achat et enregistre le prix d'entrée
                    bot_runtime_state["has_position"] = True
                    logger.info(f"🚀 ACHAT simulé à {bot_runtime_state['buy_price']:.2f} $")
                    # Note: Le capital réel n'est pas déduit ici, il sera ajusté à la vente.
                    
            elif bot_runtime_state["has_position"]:
                # --- Conditions de VENTE ---
                # Simulation de Take Profit (+1%)
                if bot_runtime_state["current_price"] >= bot_runtime_state["buy_price"] * 1.01:
                    profit_pct_target = 1.0 # 1% de profit
                    log_trade("VENTE", bot_runtime_state["current_price"], profit_pct=profit_pct_target, reason="TAKE_PROFIT")
                    logger.info(f"📈 VENTE TAKE PROFIT à {bot_runtime_state['current_price']:.2f} $")
                    bot_runtime_state["has_position"] = False
                    bot_runtime_state["buy_price"] = 0.0 # Réinitialise le prix d'achat pour la prochaine décision
                    
                # Simulation de Stop Loss (-0.5%)
                elif bot_runtime_state["current_price"] <= bot_runtime_state["buy_price"] * 0.995:
                    loss_pct_target = -0.5 # 0.5% de perte
                    log_trade("VENTE", bot_runtime_state["current_price"], profit_pct=loss_pct_target, reason="STOP_LOSS")
                    logger.info(f"📉 VENTE STOP LOSS à {bot_runtime_state['current_price']:.2f} $")
                    bot_runtime_state["has_position"] = False
                    bot_runtime_state["buy_price"] = 0.0 # Réinitialise le prix d'achat pour la prochaine décision

        except Exception as e:
            error_msg = f"Erreur dans la boucle du bot : {type(e).__name__} - {e}"
            logger.error(error_msg, exc_info=True)
            bot_runtime_state["last_error"] = error_msg
            bot_runtime_state["status"] = "Erreur inconnue"
            await asyncio.sleep(10) 
            
        if bot_runtime_state["running"]:
            await asyncio.sleep(5) 

    logger.info("Moteur du bot arrêté.")
    bot_runtime_state["status"] = "Arrêté"

# --- Événement de démarrage de l'application FastAPI ---
@app.on_event("startup")
async def startup_event():
    """Initialise la base de données et démarre le bot si configuré pour."""
    logger.info("Application démarrée. Initialisation de la base de données...")
    init_db() # Appelle init_db au démarrage

    # Optionnel: Démarrer le bot automatiquement au lancement de l'application
    # Si vous voulez que le bot démarre automatiquement, décommentez les lignes suivantes :
    # if not bot_runtime_state["running"]:
    #     logger.info("Démarrage automatique du bot...")
    #     bot_runtime_state["running"] = True
    #     bot_runtime_state["status"] = "Démarrage..."
    #     asyncio.create_task(run_bot_logic())
    # else:
    #     logger.warning("Le bot est déjà en cours d'exécution (état mémorisé ?).")

# --- Routes API FastAPI ---

@app.get("/")
async def read_root(request: Request):
    """Affiche la page d'accueil avec les statistiques du bot et l'historique des trades."""
    formatted_trades = []
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # Récupère les 100 derniers trades pour l'affichage
        cursor.execute("SELECT id, asset, type, price, amount, entry_price, exit_price, profit_pct, entry_time, exit_time, reason FROM trades ORDER BY id DESC LIMIT 100")
        trades = cursor.fetchall()
        
        for trade in trades:
            # Formatage pour l'affichage dans le template, en s'assurant que toutes les valeurs sont sérialisables
            formatted_trades.append({
                "id": trade[0], 
                "asset": trade[1], 
                "type": trade[2], 
                "price": f"{trade[3]:.2f}" if trade[3] is not None else "N/A",
                "amount": f"{trade[4]:.6f}" if trade[4] is not None else "N/A",
                "entry_price": f"{trade[5]:.2f}" if trade[5] is not None else "N/A",
                "exit_price": f"{trade[6]:.2f}" if trade[6] is not None else "N/A",
                "profit_pct": f"{trade[7]:.2f}%" if trade[7] is not None else "N/A",
                "entry_time": trade[8] if trade[8] else "N/A", 
                "exit_time": trade[9] if trade[9] else "N/A",
                "reason": trade[10]
            })
            
    except sqlite3.Error as e:
        # Si la table n'existe pas encore (ce qui ne devrait plus arriver avec init_db() au startup)
        if "no such table: trades" in str(e):
            logger.warning("La table 'trades' n'existe pas encore. Attendez que le bot démarre ou initialisez-la.")
        else:
            logger.error(f"Erreur lors de la récupération des trades depuis la BDD : {e}")
        formatted_trades = [] # Retourne une liste vide en cas d'erreur
    finally:
        if conn:
            conn.close()
            
    # Assure que toutes les valeurs dans get_bot_state() sont sérialisables (déjà fait dans la fonction)
    bot_state_data = get_bot_state()

    return templates.TemplateResponse("index.html", {
        "request": request, 
        "bot_state": bot_state_data, 
        "trades": formatted_trades
    })

@app.post("/start")
async def start_bot():
    """Démarre le bot en tâche de fond."""
    global bot_runtime_state
    if not bot_runtime_state["running"]:
        bot_runtime_state["running"] = True
        bot_runtime_state["status"] = "Démarrage..."
        # Lancer la boucle principale en tâche de fond
        asyncio.create_task(run_bot_logic())
        return {"message": "Bot démarré. La boucle de trading est en cours d'exécution."}
    else:
        return {"message": "Le bot est déjà en cours d'exécution."}

@app.post("/stop")
async def stop_bot():
    """Arrête le bot."""
    global bot_runtime_state
    if bot_runtime_state["running"]:
        bot_runtime_state["running"] = False
        bot_runtime_state["status"] = "Arrêt en cours..."
        return {"message": "Signal d'arrêt envoyé au bot. Il s'arrêtera proprement lors de la prochaine itération."}
    else:
        return {"message": "Le bot est déjà arrêté."}

@app.get("/stats")
def get_stats():
    """Retourne les statistiques actuelles du bot."""
    return get_bot_state()

# --- Point d'entrée pour exécuter directement (optionnel) ---
if __name__ == "__main__":
    import uvicorn
    # Démarrer l'application FastAPI avec Uvicorn
    # Pour le développement local, vous pouvez utiliser ceci.
    # Pour le déploiement sur Railway, le Procfile est utilisé.
    logger.info("Lancement de l'application en mode développement avec Uvicorn...")
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

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
# Chemin absolu pour s'assurer que le dossier est trouvé quel que soit l'endroit où le script est exécuté
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- Initialisation de l'Application FastAPI ---
app = FastAPI()

# --- Importation des Modules Locaux ---
# Assurez-vous que 'core' est un package Python (contient __init__.py)
try:
    from core.market import market_fetcher # market_fetcher doit être une instance dans core/market.py
except ImportError as e:
    logger.error(f"Erreur d'importation : {e}. Assurez-vous que le dossier 'core' existe et contient 'market.py'.")
    # Dans un environnement de déploiement, cette erreur empêcherait le démarrage.

# --- Variables Globales et État du Bot ---
bot_runtime_state = {
    "running": False,
    "status": "Arrêté",
    "current_price": 0.00,
    "buy_price": 0.00, # Prix d'achat pour la logique TP/SL
    "has_position": False,
    "current_capital": 1000.00,
    "initial_capital": 1000.00,
    "last_error": None,
    "entry_time_log": None, # Timestamp de l'entrée en position
    "last_entry_price": None # Prix d'entrée pour le trade actuel
}

# --- Base de Données SQLite ---
DB_NAME = "trading_bot.db"

def ensure_db_initialized():
    """
    S'assure que la base de données et la table 'trades' existent.
    Appelée avant toute opération DB.
    """
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset TEXT NOT NULL,
                type TEXT NOT NULL, -- 'ACHAT' ou 'VENTE'
                price REAL NOT NULL, -- Prix actuel lors de l'action (achat ou vente)
                amount REAL, -- Quantité si applicable (non utilisé dans simulation actuelle)
                entry_price REAL, -- Prix d'entrée enregistré pour ce trade (pour calcul de profit)
                exit_price REAL, -- Prix de sortie lors de la vente
                profit_pct REAL, -- Pourcentage de profit (ou perte) lors de la vente
                entry_time TEXT, -- Timestamp de l'entrée en position
                exit_time TEXT, -- Timestamp de la sortie de position
                reason TEXT -- Raison de la vente (e.g., 'TAKE_PROFIT', 'STOP_LOSS')
            )
        """)
        conn.commit()
        logger.info("Base de données 'trading_bot.db' et table 'trades' sont prêtes.")
    except sqlite3.Error as e:
        logger.error(f"Erreur critique lors de l'initialisation de la base de données : {e}")
        # Si la DB ne peut pas être initialisée, il est probable que le bot ne puisse pas fonctionner.
        # On pourrait choisir de stopper le bot ici ou de continuer en espérant que le problème se résolve.
        raise # Relance l'exception pour arrêter le démarrage si la DB est essentielle.
    finally:
        if conn:
            conn.close()

def log_trade(trade_type, price, profit_pct=None, reason="SIGNAL"):
    """
    Enregistre un trade dans la base de données SQLite et met à jour l'état du bot.
    """
    current_time_str = datetime.now().isoformat()
    asset = "BTC/USDT" # Symbole fixe pour l'instant
    conn = None 

    try:
        # Assure que la DB est prête avant d'insérer
        ensure_db_initialized() 
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        entry_price_for_db = bot_runtime_state.get("last_entry_price")
        entry_time_for_db = bot_runtime_state.get("entry_time_log")

        if trade_type == "ACHAT":
            bot_runtime_state["last_entry_price"] = price # Enregistre le prix d'achat actuel pour référence future
            bot_runtime_state["entry_time_log"] = current_time_str # Enregistre le temps d'achat actuel
            bot_runtime_state["buy_price"] = price # Met à jour le prix de référence pour TP/SL
            bot_runtime_state["has_position"] = True # Indique qu'une position est ouverte
            
            # Optionnel: Loguer l'achat directement si vous avez des colonnes pour cela dans la BDD
            # Pour l'instant, on se concentre sur la vente qui inclut le P&L.
            logger.info(f"-> ACHAT {asset} à {price:.2f} $ (Prix d'entrée enregistré: {entry_price_for_db:.2f} @ {entry_time_for_db})")
            
        elif trade_type == "VENTE":
            if entry_price_for_db is None or entry_time_for_db is None:
                logger.error("Erreur critique : Prix d'entrée ou temps d'entrée manquant pour loguer une vente. Trade ignoré.")
                return 

            # Calcul du profit/perte en pourcentage basé sur le prix d'entrée enregistré
            final_profit_pct = 0.0
            if entry_price_for_db and price:
                final_profit_pct = ((price - entry_price_for_db) / entry_price_for_db) * 100
            
            # Utilise le profit_pct passé en argument s'il est fourni (ex: pour des targets fixes), sinon utilise le calculé.
            # La logique actuelle utilise des targets fixes (1% TP, -0.5% SL) donc profit_pct est déjà défini.
            # Si profit_pct argument est N/A ou autre, on utilise le calculé.
            final_profit_pct = profit_pct if profit_pct is not None else final_profit_pct

            cursor.execute("""
                INSERT INTO trades (asset, type, price, entry_price, exit_price, profit_pct, entry_time, exit_time, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (asset, trade_type, price, entry_price_for_db, price, final_profit_pct, entry_time_for_db, current_time_str, reason))
            
            icon = "🔴" if final_profit_pct < 0 else "🔵"
            logger.info(f"{icon} VENTE {asset} à {price:.2f} $ | Raison: {reason} | P&L: {final_profit_pct:.2f}% (Entrée: {entry_price_for_db:.2f} @ {entry_time_for_db})")
            
            # --- Mise à jour du capital en mémoire ---
            # Ajuste le capital avec le profit/perte du trade actuel
            capital_adjustment = bot_runtime_state["current_capital"] * (final_profit_pct / 100.0)
            bot_runtime_state["current_capital"] += capital_adjustment
            bot_runtime_state["current_capital"] = round(bot_runtime_state["current_capital"], 2)
            logger.info(f"Capital mis à jour: {bot_runtime_state['current_capital']:.2f} $")

            # Réinitialiser les états liés au trade en cours
            bot_runtime_state["has_position"] = False
            bot_runtime_state["buy_price"] = 0.0
            bot_runtime_state["last_entry_price"] = None
            bot_runtime_state["entry_time_log"] = None

        conn.commit()
        
    except sqlite3.Error as e:
        logger.error(f"Erreur lors de l'opération sur la base de données : {e}")
        bot_runtime_state["last_error"] = f"DB Error: {e}"
    except Exception as e:
        logger.error(f"Erreur inattendue lors du log du trade : {type(e).__name__} - {e}")
        bot_runtime_state["last_error"] = f"Trade Log Error: {e}"
    finally:
        if conn:
            conn.close()

def get_bot_state_for_template():
    """
    Retourne un dictionnaire d'état du bot formaté pour être utilisé dans le template Jinja2.
    Garantit que toutes les valeurs sont des types sérialisables et formatées.
    """
    return {
        "running": bot_runtime_state["running"],
        "status": bot_runtime_state["status"],
        # Formatte les nombres en chaînes avec 2 décimales, ou 'N/A' si non applicable
        "current_price": f"{bot_runtime_state['current_price']:.2f}" if bot_runtime_state['current_price'] else "N/A",
        "buy_price": f"{bot_runtime_state['buy_price']:.2f}" if bot_runtime_state["has_position"] and bot_runtime_state['buy_price'] else "N/A",
        "has_position": bot_runtime_state["has_position"],
        "current_capital": f"{bot_runtime_state['current_capital']:.2f}",
        "initial_capital": f"{bot_runtime_state['initial_capital']:.2f}",
        "last_error": bot_runtime_state["last_error"] if bot_runtime_state["last_error"] else "Aucune erreur récente.",
        "entry_time_log": bot_runtime_state["entry_time_log"] if bot_runtime_state["entry_time_log"] else "N/A",
        "last_entry_price": f"{bot_runtime_state['last_entry_price']:.2f}" if bot_runtime_state["last_entry_price"] else "N/A",
    }

# --- Logique Principale du Bot ---
async def run_bot_logic():
    """Boucle principale d'exécution du bot."""
    global bot_runtime_state

    logger.info("Démarrage de la boucle logique du bot...")
    bot_runtime_state["status"] = "Actif"
    bot_runtime_state["running"] = True

    # Assure que le capital est correct au démarrage de la boucle
    if bot_runtime_state["current_capital"] == 0.0 and bot_runtime_state["initial_capital"] > 0:
        bot_runtime_state["current_capital"] = bot_runtime_state["initial_capital"]
        logger.info(f"Capital réinitialisé à {bot_runtime_state['current_capital']:.2f} $")
        
    logger.info(f"Moteur démarré avec capital actuel: {bot_runtime_state['current_capital']:.2f} $")

    while bot_runtime_state["running"]:
        try:
            # --- 1. Récupération du prix ---
            current_price = market_fetcher.get_current_price("BTC/USDT") 

            if current_price is None or current_price <= 0:
                logger.warning(f"Prix CoinGecko invalide ou non récupéré (valeur: {current_price}). Réessai dans 10s.")
                bot_runtime_state["status"] = "Erreur Prix"
                bot_runtime_state["last_error"] = "Prix CoinGecko invalide ou non récupéré."
                await asyncio.sleep(10) 
                continue

            bot_runtime_state["current_price"] = current_price
            bot_runtime_state["status"] = "Actif" # S'assurer que le statut est 'Actif' si le prix est bon
            bot_runtime_state["last_error"] = None # Effacer l'erreur précédente si le prix est bon
            logger.debug(f"Prix BTC/USDT actuel: {bot_runtime_state['current_price']:.2f} $")

            # ==========================================
            # 2. STRATÉGIE DE TRADING (Simulation)
            # ==========================================
            
            # Si on n'a pas de position ouverte
            if not bot_runtime_state["has_position"]:
                # Condition d'ACHAT simulée: Acheter au premier prix valide quand on n'a pas de position
                # Dans une vraie stratégie, il y aurait ici une analyse (moyennes mobiles, RSI, etc.)
                if bot_runtime_state["last_entry_price"] is None: # S'assurer qu'on n'est pas déjà dans une logique d'achat
                    logger.info(f"💡 Signal d'ACHAT détecté ! Prix actuel: {bot_runtime_state['current_price']:.2f} $")
                    # Log l'achat et enregistre le prix/temps d'entrée
                    log_trade("ACHAT", bot_runtime_state["current_price"]) 
                    # Le capital n'est pas déduit ici, seulement lors de la vente.
                    
            # Si on a une position ouverte
            elif bot_runtime_state["has_position"]:
                # Condition de VENTE : Take Profit (+1%)
                # Utilise le prix d'achat enregistré pour le calcul du profit
                if bot_runtime_state["current_price"] >= bot_runtime_state["buy_price"] * 1.01:
                    log_trade("VENTE", bot_runtime_state["current_price"], profit_pct=1.0, reason="TAKE_PROFIT")
                    
                # Condition de VENTE : Stop Loss (-0.5%)
                elif bot_runtime_state["current_price"] <= bot_runtime_state["buy_price"] * 0.995:
                    log_trade("VENTE", bot_runtime_state["current_price"], profit_pct=-0.5, reason="STOP_LOSS")

        except Exception as e:
            error_msg = f"Erreur dans la boucle principale du bot : {type(e).__name__} - {e}"
            logger.error(error_msg, exc_info=True)
            bot_runtime_state["last_error"] = error_msg
            bot_runtime_state["status"] = "Erreur Boucle"
            # Petite pause pour éviter de surcharger en cas d'erreur fréquente
            await asyncio.sleep(5) 
            
        # Pause entre chaque itération de la boucle principale (sauf si une erreur a causé une pause plus longue)
        if bot_runtime_state["running"]:
            await asyncio.sleep(5) 

    logger.info("Boucle logique du bot terminée (bot arrêté).")
    bot_runtime_state["status"] = "Arrêté"
    # Réinitialisation des états liés au trade en cours lors de l'arrêt
    bot_runtime_state["has_position"] = False
    bot_runtime_state["buy_price"] = 0.0
    bot_runtime_state["last_entry_price"] = None
    bot_runtime_state["entry_time_log"] = None

# --- Événement de démarrage de l'application FastAPI ---
@app.on_event("startup")
async def startup_event():
    """Initialise la base de données et démarre le bot si nécessaire."""
    logger.info("Événement startup : Initialisation de la base de données...")
    try:
        ensure_db_initialized() # Assure que DB et table sont prêtes AVANT de démarrer le bot.
        logger.info("Base de données prête.")
    except Exception as e:
        logger.error(f"Échec de l'initialisation de la base de données au démarrage : {e}. L'application pourrait ne pas fonctionner correctement.")
        # On laisse l'application continuer mais on logue l'erreur.

    # Démarrer le bot en tâche de fond s'il n'est pas déjà en cours
    if not bot_runtime_state["running"]:
        logger.info("Démarrage du bot en tâche de fond...")
        bot_runtime_state["running"] = True
        bot_runtime_state["status"] = "Démarrage..."
        asyncio.create_task(run_bot_logic())
    else:
        logger.warning("Le bot est déjà indiqué comme en cours d'exécution.")


# --- Routes API FastAPI ---

@app.get("/")
async def read_root(request: Request):
    """Affiche la page d'accueil avec les statistiques du bot et l'historique des trades."""
    formatted_trades = []
    try:
        # Assure que la DB est prête avant de lire
        ensure_db_initialized() 
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        # Récupère les 100 derniers trades pour l'affichage
        cursor.execute("SELECT id, asset, type, price, amount, entry_price, exit_price, profit_pct, entry_time, exit_time, reason FROM trades ORDER BY id DESC LIMIT 100")
        trades = cursor.fetchall()
        
        for trade in trades:
            # Formatage pour Jinja2, en s'assurant que tout est une chaîne ou un nombre simple
            formatted_trades.append({
                "id": trade[0], 
                "asset": trade[1] or "N/A", 
                "type": trade[2] or "N/A", 
                "price": f"{trade[3]:.2f}" if trade[3] is not None else "N/A",
                "amount": f"{trade[4]:.6f}" if trade[4] is not None else "N/A", # Moins pertinent pour l'instant
                "entry_price": f"{trade[5]:.2f}" if trade[5] is not None else "N/A",
                "exit_price": f"{trade[6]:.2f}" if trade[6] is not None else "N/A",
                "profit_pct": f"{trade[7]:.2f}%" if trade[7] is not None else "N/A",
                "entry_time": trade[8] or "N/A", 
                "exit_time": trade[9] or "N/A",
                "reason": trade[10] or "Non spécifié"
            })
            
    except sqlite3.Error as e:
        # Si la table n'existe pas encore, c'est que ensure_db_initialized() a échoué ou n'a pas été appelée à temps.
        logger.error(f"Erreur SQLite lors de la récupération des trades : {e}")
        formatted_trades = [] # Retourne une liste vide pour éviter le crash du template
    except Exception as e:
        logger.error(f"Erreur inattendue lors de la récupération des trades : {type(e).__name__} - {e}")
        formatted_trades = []
    finally:
        if conn:
            conn.close()
            
    # Obtenir l'état du bot DÉJÀ FORMATÉ pour Jinja2
    bot_state_data = get_bot_state_for_template()

    # Rendu du template avec le contexte préparé
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "bot_state": bot_state_data, 
        "trades": formatted_trades
    })

@app.post("/start")
async def start_bot_route():
    """Démarre le bot via une requête POST."""
    global bot_runtime_state
    if not bot_runtime_state["running"]:
        bot_runtime_state["running"] = True
        bot_runtime_state["status"] = "Démarrage..."
        asyncio.create_task(run_bot_logic())
        logger.info("Route /start appelée : Bot démarré.")
        return {"message": "Bot démarré. La boucle de trading est en cours d'exécution."}
    else:
        logger.warning("Route /start appelée mais le bot est déjà en cours d'exécution.")
        return {"message": "Le bot est déjà en cours d'exécution."}

@app.post("/stop")
async def stop_bot_route():
    """Arrête le bot via une requête POST."""
    global bot_runtime_state
    if bot_runtime_state["running"]:
        bot_runtime_state["running"] = False
        bot_runtime_state["status"] = "Arrêt en cours..."
        logger.info("Route /stop appelée : Signal d'arrêt envoyé au bot.")
        return {"message": "Signal d'arrêt envoyé au bot. Il s'arrêtera proprement lors de la prochaine itération."}
    else:
        logger.warning("Route /stop appelée mais le bot est déjà arrêté.")
        return {"message": "Le bot est déjà arrêté."}

@app.get("/stats")
def get_stats_route():
    """Retourne les statistiques actuelles du bot (format JSON)."""
    return get_bot_state_for_template()

# --- Point d'entrée pour exécuter directement (pour le développement local) ---
if __name__ == "__main__":
    import uvicorn
    logger.info("Lancement de l'application en mode développement avec Uvicorn...")
    # Lance uvicorn. N'oubliez pas de configurer le port si nécessaire (e.g., PORT=8000)
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)

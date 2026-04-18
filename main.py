import asyncio
import sqlite3
import os
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
import logging
from datetime import datetime

# --- Configuration du Logging ---
# Utilise un format plus détaillé pour les logs
LOG_FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger(__name__)

# --- Configuration du Dossier Templates ---
# Chemin absolu 100% fiable pour le dossier 'templates'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- Initialisation de l'Application FastAPI ---
app = FastAPI()

# --- Importation des Modules Locaux ---
# Assurez-vous que les chemins d'importation correspondent à votre structure de dossiers.
# Si main.py est dans le dossier 'core', ces imports doivent fonctionner tels quels depuis la racine du projet.
try:
    from core.engine import PaperTradingEngine
    from core.market import market_fetcher # Assurez-vous que market_fetcher est bien une instance dans market.py
except ImportError as e:
    logger.error(f"Erreur d'importation : {e}. Assurez-vous que la structure des dossiers est correcte et que les fichiers existent.")
    # Si une erreur d'importation se produit, il est inutile de continuer.
    # Dans un déploiement réel, cela pourrait entraîner un crash silencieux si non géré.
    # Ici, on va juste logger et laisser potentiellement l'application échouer à démarrer.

# --- Variables Globales et État du Bot ---
# Utilisation d'un dictionnaire pour gérer l'état du bot de manière centralisée
bot_runtime_state = {
    "running": False,
    "status": "Arrêté", # Statut : "Arrêté", "Actif", "En pause", "Erreur Prix CoinGecko", "Erreur inconnue"
    "current_price": 0.00,
    "buy_price": 0.00, # Prix auquel le dernier achat a été effectué
    "has_position": False, # Booléen pour savoir si une position est actuellement ouverte
    "current_capital": 1000.00, # Capital initial pour le paper trading
    "initial_capital": 1000.00, # Stocke le capital initial
    "last_error": None,
    "exchange": None, # Pour CCXT si vous l'utilisez plus tard
    "trade_history": [] # Pour stocker les trades directement en mémoire pour l'affichage rapide
}

# --- Initialisation de la Base de Données SQLite (pour l'historique des trades) ---
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
                amount REAL, -- Montant seulement pour les achats, ou calculé pour les ventes
                entry_price REAL, -- Prix d'entrée si type='VENTE'
                exit_price REAL, -- Prix de sortie si type='VENTE'
                profit_pct REAL, -- Pourcentage de profit si type='VENTE'
                entry_time TEXT, -- Timestamp de l'entrée
                exit_time TEXT, -- Timestamp de la sortie
                reason TEXT -- Raison de la vente (e.g., 'SIGNAL', 'TAKE_PROFIT', 'STOP_LOSS')
            )
        """)
        conn.commit()
        logger.info("Base de données 'trading_bot.db' initialisée et table 'trades' prête.")
    except sqlite3.Error as e:
        logger.error(f"Erreur lors de l'initialisation de la base de données : {e}")
    finally:
        if conn:
            conn.close()

def log_trade(trade_type, price, profit_or_amount=None, entry_price=None, exit_time=None, reason="SIGNAL"):
    """
    Enregistre un trade dans la base de données SQLite.
    - Si type='ACHAT': profit_or_amount est le montant acheté. entry_price doit être fourni.
    - Si type='VENTE': profit_or_amount est le profit (ou profit_pct). entry_price doit être fourni.
    """
    current_time_str = datetime.now().isoformat()
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        
        asset = "BTC/USDT" # Symbole fixe pour l'instant
        entry_time_str = bot_runtime_state.get("entry_time_log", current_time_str) # Utilise le temps d'entrée enregistré

        if trade_type == "ACHAT":
            amount = profit_or_amount # Dans le cas d'un achat, c'est le montant
            # Calculer le montant basé sur le capital et le prix d'achat s'il n'est pas donné
            if amount is None:
                amount = bot_runtime_state["current_capital"] / price
                logger.warning(f"Montant d'achat non fourni, calculé dynamiquement : {amount:.6f}")
            
            cursor.execute("""
                INSERT INTO trades (asset, type, price, amount, entry_time, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (asset, trade_type, price, amount, entry_time_str, reason))
            logger.info(f"✅ Log : ACHAT {asset} à {price:.2f} $ | Montant: {amount:.6f}")
            
            # Sauvegarde pour la récupération rapide du prix d'entrée
            bot_runtime_state["entry_time_log"] = current_time_str # Mise à jour pour le prochain trade
            bot_runtime_state["last_entry_price"] = price # Sauvegarde du prix d'entrée pour le calcul du profit
            
        elif trade_type == "VENTE":
            # Si profit_or_amount est un pourcentage
            if isinstance(profit_or_amount, (int, float)) and profit_or_amount > 1: # Supposition : si > 1, c'est un montant, pas un %
                 profit_pct = ((price - entry_price) / entry_price) * 100 if entry_price else 0
            else: # C'est déjà un pourcentage
                 profit_pct = profit_or_amount
            
            # Utilisation du prix d'entrée enregistré
            entry_price_used = bot_runtime_state.get("last_entry_price", entry_price)
            if entry_price_used is None:
                logger.error("Impossible de calculer le profit sans prix d'entrée.")
                profit_pct = 0.0 # Ou gérer cette erreur autrement

            # Calcul du profit en dollar
            profit_usd = (entry_price_used * (profit_pct / 100)) if entry_price_used else 0
            
            cursor.execute("""
                INSERT INTO trades (asset, type, price, entry_price, exit_price, profit_pct, entry_time, exit_time, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (asset, trade_type, price, entry_price_used, price, profit_pct, entry_time_str, current_time_str, reason))
            
            icon = "🔴" if profit_pct < 0 else "🔵"
            logger.info(f"{icon} Log : VENTE {asset} à {price:.2f} $ | Raison: {reason} | P&L: {profit_pct:.2f}% | Profit$: {profit_usd:.2f}")
            
            # Réinitialiser le prix d'entrée enregistré après une vente
            bot_runtime_state["last_entry_price"] = None
            bot_runtime_state["entry_time_log"] = None

        conn.commit()
        
        # Mise à jour du capital en mémoire après un trade
        if trade_type == "ACHAT":
            # Le capital sera mis à jour lors de la vente
            pass
        elif trade_type == "VENTE" and entry_price_used is not None:
            # Recalculer le capital basé sur le prix d'entrée, le profit et le montant (si connu)
            # Plus simple: ajuster le capital en fonction du profit réalisé
            profit_amount = bot_runtime_state["current_capital"] * (profit_pct / 100) if bot_runtime_state["current_capital"] else 0
            # Si le profit est calculé en dollar, on l'ajoute directement. Sinon, on ajuste le capital total.
            # Ici, on utilise le profit en % pour ajuster le capital total
            adjusted_profit = bot_runtime_state["current_capital"] * (profit_pct / 100.0)
            bot_runtime_state["current_capital"] += adjusted_profit
            bot_runtime_state["current_capital"] = round(bot_runtime_state["current_capital"], 2)


    except sqlite3.Error as e:
        logger.error(f"Erreur lors de l'enregistrement du trade : {e}")
    finally:
        if conn:
            conn.close()


# --- Fonctions utilitaires pour l'état du Bot ---
def get_bot_state():
    """Retourne l'état actuel du bot pour l'API."""
    # Vous pouvez ici récupérer les trades depuis la BDD pour un historique plus complet si nécessaire
    # Pour l'instant, on utilise l'état en mémoire.
    return {
        "running": bot_runtime_state["running"],
        "status": bot_runtime_state["status"],
        "current_price": f"{bot_runtime_state['current_price']:.2f}",
        "buy_price": f"{bot_runtime_state['buy_price']:.2f}" if bot_runtime_state["has_position"] else "N/A",
        "has_position": bot_runtime_state["has_position"],
        "current_capital": f"{bot_runtime_state['current_capital']:.2f}",
        "initial_capital": f"{bot_runtime_state['initial_capital']:.2f}",
        "last_error": bot_runtime_state["last_error"],
        # Optionnel: ajouter plus de détails si nécessaire
    }

# --- Logique Principale du Bot ---
async def run_bot_logic():
    """Boucle principale d'exécution du bot avec logs pour le debugging."""
    global bot_runtime_state # Accès à la variable globale d'état

    logger.info("Démarrage de la boucle logique du bot...")
    init_db() # Assure que la DB est prête au démarrage

    bot_runtime_state["status"] = "Actif"
    bot_runtime_state["running"] = True # Marque le bot comme étant en cours d'exécution
    logger.info(f"Moteur démarré avec un capital de {bot_runtime_state['current_capital']:.2f} $ (simulation paper trading)")

    while bot_runtime_state["running"]:
        try:
            # --- 1. Récupération du prix via CoinGecko ---
            logger.debug("Tentative de récupération du prix BTC/USDT via CoinGecko...")
            # Utilisation du market_fetcher importé (attendu : une instance déjà créée dans core/market.py)
            # market_fetcher.get_current_price doit retourner le prix en USDT
            current_price = market_fetcher.get_current_price("BTC/USDT") 

            if current_price is None or current_price == 0: # Vérifie aussi si le prix est 0
                logger.error("Impossible de récupérer le prix via CoinGecko (ou prix invalide). Le bot va attendre avant de réessayer.")
                bot_runtime_state["status"] = "Erreur Prix CoinGecko"
                bot_runtime_state["last_error"] = "Prix CoinGecko invalide ou non récupéré."
                await asyncio.sleep(10) # Pause plus longue en cas d'échec
                continue # Passe à l'itération suivante

            # Mise à jour de l'état du bot avec le nouveau prix
            bot_runtime_state["current_price"] = current_price
            bot_runtime_state["status"] = "Actif" # Rétablit le statut si une erreur de prix avait eu lieu
            bot_runtime_state["last_error"] = None # Efface les erreurs précédentes si la requête réussit
            logger.info(f"Prix BTC/USDT actuel : {bot_runtime_state['current_price']:.2f} $")

            # ==========================================
            # 2. STRATÉGIE DE TRADING (Simulation)
            # ==========================================
            # Cette partie simule une stratégie simple de Take Profit et Stop Loss
            
            if not bot_runtime_state["has_position"]:
                # --- Condition d'ACHAT ---
                # Ici, vous intégreriez votre vraie logique de stratégie (e.g., depuis strategy_1.py)
                # Pour l'instant, on simule un achat basé sur un simple signal
                
                # Exemple de signal simple : on achète si le prix est inférieur à un certain seuil (ici, arbitraire)
                # ou si un indicateur X devient vert (ce qui serait implémenté dans une vraie stratégie)
                
                # On simule un achat dès que le bot démarre ou après une vente
                if bot_runtime_state["buy_price"] == 0.0: # Si pas de prix d'entrée enregistré
                    bot_runtime_state["buy_price"] = bot_runtime_state["current_price"]
                    bot_runtime_state["has_position"] = True
                    # Enregistre le trade d'achat dans la BDD et met à jour le temps d'entrée
                    log_trade("ACHAT", bot_runtime_state["current_price"], reason="DEMARRAGE_BOT") 
                    logger.info(f"🚀 ACHAT simulé {bot_runtime_state['current_price']:.2f} $ (Initial Capital: {bot_runtime_state['current_capital']:.2f})")
                    # Si vous avez besoin de calculer le montant exact ici :
                    # amount_bought = bot_runtime_state["current_capital"] / bot_runtime_state["current_price"]
                    # bot_runtime_state["current_capital"] -= amount_bought * bot_runtime_state["current_price"] # Ceci est faux, le capital doit être ajusté à la vente
                    # Il est plus simple de loguer le prix d'entrée et de calculer le profit à la sortie

            elif bot_runtime_state["has_position"]:
                # --- Conditions de VENTE ---
                # Simulation de Take Profit (+1%)
                if bot_runtime_state["current_price"] >= bot_runtime_state["buy_price"] * 1.01:
                    profit_pct = 1.0 # 1% de profit
                    # Calcul du profit en dollar pour l'affichage et la mise à jour du capital
                    profit_usd = bot_runtime_state["current_capital"] * (profit_pct / 100.0)
                    bot_runtime_state["current_capital"] += profit_usd
                    bot_runtime_state["current_capital"] = round(bot_runtime_state["current_capital"], 2)
                    
                    log_trade("VENTE", bot_runtime_state["current_price"], profit_pct=profit_pct, entry_price=bot_runtime_state["buy_price"], reason="TAKE_PROFIT")
                    logger.info(f"📈 VENTE TAKE PROFIT à {bot_runtime_state['current_price']:.2f} $ | Profit: {profit_pct:.2f}% ({profit_usd:.2f}$)")
                    
                    bot_runtime_state["has_position"] = False
                    bot_runtime_state["buy_price"] = 0.0 # Réinitialise le prix d'entrée
                    
                # Simulation de Stop Loss (-0.5%)
                elif bot_runtime_state["current_price"] <= bot_runtime_state["buy_price"] * 0.995:
                    profit_pct = -0.5 # 0.5% de perte
                    # Calcul de la perte en dollar pour la mise à jour du capital
                    loss_usd = bot_runtime_state["current_capital"] * (abs(profit_pct) / 100.0)
                    bot_runtime_state["current_capital"] -= loss_usd
                    bot_runtime_state["current_capital"] = round(bot_runtime_state["current_capital"], 2)

                    log_trade("VENTE", bot_runtime_state["current_price"], profit_pct=profit_pct, entry_price=bot_runtime_state["buy_price"], reason="STOP_LOSS")
                    logger.info(f"📉 VENTE STOP LOSS à {bot_runtime_state['current_price']:.2f} $ | Perte: {abs(profit_pct):.2f}% ({loss_usd:.2f}$)")
                    
                    bot_runtime_state["has_position"] = False
                    bot_runtime_state["buy_price"] = 0.0 # Réinitialise le prix d'entrée

            # ==========================================

        # --- Gestion des erreurs générales ---
        except Exception as e:
            error_msg = f"Erreur dans la boucle du bot : {type(e).__name__} - {e}"
            logger.error(error_msg, exc_info=True)
            bot_runtime_state["last_error"] = error_msg
            bot_runtime_state["status"] = "Erreur inconnue"
            # On peut choisir de continuer ou de s'arrêter en cas d'erreur inconnue
            # Ici, on continue avec une pause plus longue
            await asyncio.sleep(10) 
            
        # --- Pause entre les itérations ---
        # Attend avant la prochaine vérification si le bot tourne toujours
        if bot_runtime_state["running"]:
            # Utilise un intervalle plus court pour une réactivité accrue, ajustable
            await asyncio.sleep(5) 

    # Le bot s'arrête ici proprement
    logger.info("Moteur du bot arrêté (boucle 'while bot_runtime_state[\"running\"]' terminée).")
    bot_runtime_state["status"] = "Arrêté"
    # Si vous utilisiez CCXT pour le trading réel, appelez close_exchange() ici.
    # await close_exchange() 
    logger.info("Moteur arrêté.")

# --- Routes API FastAPI ---

@app.get("/")
async def read_root(request: Request):
    """Affiche la page d'accueil avec les statistiques du bot."""
    # Récupère les trades depuis la BDD pour les afficher
    try:
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM trades ORDER BY id DESC LIMIT 100") # Récupère les 100 derniers trades
        trades = cursor.fetchall()
        # Formate les trades pour une meilleure lisibilité si nécessaire
        formatted_trades = []
        for trade in trades:
            # Assurez-vous que les indices correspondent à votre schéma de table
            formatted_trades.append({
                "id": trade[0], "asset": trade[1], "type": trade[2], "price": f"{trade[3]:.2f}",
                "amount": f"{trade[4]:.6f}" if trade[4] else "N/A",
                "entry_price": f"{trade[5]:.2f}" if trade[5] else "N/A",
                "exit_price": f"{trade[6]:.2f}" if trade[6] else "N/A",
                "profit_pct": f"{trade[7]:.2f}%" if trade[7] else "N/A",
                "entry_time": trade[8], "exit_time": trade[9] if trade[9] else "N/A",
                "reason": trade[10]
            })
    except sqlite3.Error as e:
        logger.error(f"Erreur lors de la récupération des trades depuis la BDD : {e}")
        formatted_trades = []
    finally:
        if conn:
            conn.close()
            
    return templates.TemplateResponse("index.html", {"request": request, "bot_state": get_bot_state(), "trades": formatted_trades})

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
        # La boucle run_bot_logic se terminera et mettra le statut à "Arrêté"
        return {"message": "Signal d'arrêt envoyé au bot. Il s'arrêtera proprement lors de la prochaine itération."}
    else:
        return {"message": "Le bot est déjà arrêté."}

@app.get("/stats")
def get_stats():
    """Retourne les statistiques actuelles du bot."""
    # Renvoie les statistiques directement depuis l'état global
    return get_bot_state()

# --- Point d'entrée pour le serveur ASGI (souvent géré par Uvicorn via Procfile) ---
# Si vous exécutez ce fichier directement avec `python main.py`, vous pouvez décommenter ceci :
# if __name__ == "__main__":
#     import uvicorn
#     # Initialiser la DB avant de démarrer
#     init_db()
#     # Lancer l'application FastAPI
#     uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))

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
# Utilisation d'un formatage plus complet pour les logs
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
    # Lancer une erreur fatale si le module de marché est indispensable au démarrage
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
    # Si les templates ne peuvent pas être chargés, l'application ne peut pas fonctionner correctement
    raise HTTPException(status_code=500, detail="Erreur de configuration des templates.")

# --- Variables Globales et État du Bot ---
# Initialisation avec des valeurs par défaut sûres
current_price = 0.00
current_capital = 1000.00  # Capital de départ par défaut
bot_status = "Arrêté"      # Statut initial du bot
bot_running = False        # Indicateur si le bot est en cours d'exécution
trade_history_memory = []  # Stockage en mémoire des trades pour un accès rapide
bot_task = None            # Pour garder une référence à la tâche asyncio du bot

# --- Fonctions de gestion de la base de données ---

def initialize_database():
    """Crée la base de données et la table des trades si elles n'existent pas."""
    conn = None
    try:
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
        raise # Relancer l'erreur pour que l'application échoue au démarrage si la DB est indisponible
    finally:
        if conn:
            conn.close()

def add_trade(trade_data):
    """Ajoute un nouveau trade à la base de données et à l'historique en mémoire."""
    global trade_history_memory
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        cursor = conn.cursor()
        # Préparation des données pour l'insertion SQL
        # Assurez-vous que trade_data contient toutes les clés attendues
        cursor.execute(f'''
            INSERT INTO {TRADES_TABLE} (timestamp, type, symbol, entry_price, exit_price, amount, profit, status)
            VALUES (:timestamp, :type, :symbol, :entry_price, :exit_price, :amount, :profit, :status)
        ''', trade_data)
        conn.commit()
        logger.info(f"Trade ajouté : {trade_data.get('symbol')} - {trade_data.get('type')}")

        # Ajout à l'historique en mémoire (pour un affichage rapide)
        # On utilise un dictionnaire formaté pour l'affichage
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
        # Limiter la taille de l'historique en mémoire pour éviter une consommation excessive
        if len(trade_history_memory) > 100: # Garder les 100 derniers trades en mémoire
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
        cursor.execute(f'''
            SELECT timestamp, type, symbol, entry_price, exit_price, amount, profit, status
            FROM {TRADES_TABLE}
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (limit,))
        rows = cursor.fetchall()

        # Convertir les lignes en dictionnaires pour une meilleure lisibilité
        columns = [description[0] for description in cursor.description]
        for row in rows:
            # Utiliser les valeurs brutes de la DB et formater ensuite pour le template
            trade_dict = dict(zip(columns, row))
            # Formatage pour le template: s'assurer que les nombres sont des floats et les dates des strings
            trades.append({
                "timestamp": str(trade_dict.get('timestamp')),
                "type": str(trade_dict.get('type', '')),
                "symbol": str(trade_dict.get('symbol', '')),
                "entry_price": float(trade_dict.get('entry_price', 0.0) or 0.0), # Gérer les None
                "exit_price": float(trade_dict.get('exit_price', 0.0) or 0.0), # Gérer les None
                "amount": float(trade_dict.get('amount', 0.0) or 0.0),
                "profit": float(trade_dict.get('profit', 0.0) or 0.0),
                "status": str(trade_dict.get('status', 'unknown'))
            })
    except sqlite3.Error as e:
        logger.error(f"Erreur SQLite lors de la récupération des trades : {e}", exc_info=True)
        # Retourner une liste vide en cas d'erreur pour ne pas casser le rendu
        return [{"error": "Erreur de chargement des trades depuis la base de données."}]
    finally:
        if conn:
            conn.close()
    return trades


# --- Fonctions du Bot ---

async def run_bot_logic():
    """Logique principale du bot : récupérer le prix et potentiellement trader."""
    global current_price, current_capital, bot_running, bot_status
    global trade_history_memory # Assurez-vous que trade_history_memory est accessible

    while bot_running:
        try:
            # 1. Obtenir le prix actuel
            price_data = await get_current_price("BTC/USDT")
            if price_data and 'last' in price_data:
                current_price = price_data['last']
                logger.info(f"Prix actuel BTC/USDT : {current_price}")
            else:
                logger.warning("Impossible de récupérer le prix actuel du marché.")

            # 2. Logique de trading (à implémenter)
            # Exemple : si le prix atteint un certain seuil, acheter/vendre
            # Ici, on simule une action simple : si le prix est supérieur à 60000 et qu'on a du capital
            if current_price > 60000 and current_capital > 100 and bot_status == "Actif":
                logger.info(f"Seuil de prix atteint ({current_price}). Tentative d'achat simulée.")
                # Simuler l'achat
                buy_amount = 0.001 # Acheter 0.001 BTC
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
                    add_trade(new_trade) # Ajoute à la DB et à la mémoire
                    current_capital -= buy_amount * current_price
                    logger.info(f"Achat simulé : {buy_amount} BTC à {current_price}. Capital restant : {current_capital:.2f}")
                else:
                    logger.warning("Capital insuffisant pour l'achat simulé.")

            # Exemple : si un trade ouvert existe et que le prix est monté
            # Chercher un trade ouvert dans l'historique en mémoire
            open_buy_trade = next((t for t in trade_history_memory if t['status'] == 'open' and t['type'] == 'buy'), None)
            if open_buy_trade and current_price > open_buy_trade['entry_price'] * 1.05 and bot_status == "Actif": # Vendre si +5%
                logger.info(f"Seuil de vente atteint pour le trade ouvert ({current_price}). Tentative de vente simulée.")
                profit = (current_price - open_buy_trade['entry_price']) * open_buy_trade['amount']
                current_capital += open_buy_trade['amount'] * current_price # Récupérer le capital + profit
                # Mettre à jour le trade en mémoire et en DB (il faudrait une fonction update_trade)
                # Pour simplifier ici, on simule la fermeture :
                open_buy_trade['exit_price'] = current_price
                open_buy_trade['profit'] = profit
                open_buy_trade['status'] = 'closed'
                # Il faudrait ici une fonction pour mettre à jour le trade en base de données
                # Pour l'instant, on se contente de la mise à jour en mémoire et on logue.
                logger.info(f"Vente simulée : {open_buy_trade['amount']} BTC à {current_price}. Profit : {profit:.2f}. Capital total : {current_capital:.2f}")
                # Si vous avez une fonction d'update_trade, appelez-la ici.

            # Attendre avant la prochaine itération
            await asyncio.sleep(15) # Attendre 15 secondes

        except ccxt.NetworkError as e:
            logger.error(f"Erreur réseau CCXT : {e}. Réessai dans 60 secondes.")
            await asyncio.sleep(60)
        except sqlite3.Error as e:
            logger.error(f"Erreur SQLite pendant l'exécution du bot : {e}", exc_info=True)
            await asyncio.sleep(30) # Attendre avant de réessayer
        except Exception as e:
            logger.error(f"Erreur inattendue dans la logique du bot : {e}", exc_info=True)
            # Si une erreur grave survient, on pourrait envisager d'arrêter le bot
            # stop_bot() # Décommentez si nécessaire
            await asyncio.sleep(30) # Attendre avant de réessayer

def start_bot():
    """Démarre la tâche asyncio du bot."""
    global bot_running, bot_task, bot_status
    if not bot_running:
        bot_running = True
        bot_status = "Actif"
        # Lancer la tâche du bot en arrière-plan
        bot_task = asyncio.create_task(run_bot_logic())
        logger.info("Bot démarré.")
    else:
        logger.warning("Le bot est déjà en cours d'exécution.")

def stop_bot():
    """Arrête la tâche asyncio du bot."""
    global bot_running, bot_task, bot_status
    if bot_running:
        bot_running = False
        if bot_task:
            bot_task.cancel() # Annuler la tâche en cours
            bot_task = None
        bot_status = "Arrêté"
        logger.info("Bot arrêté.")
    else:
        logger.warning("Le bot n'est pas en cours d'exécution.")


# --- Routes de l'application ---

@app.get("/")
async def read_root(request: Request):
    """Route principale pour afficher le dashboard."""
    global current_capital, bot_status, current_price, trade_history_memory

    logger.info("Requête reçue pour la page d'accueil.")

    # Assurer que les variables sont des types simples pour Jinja2
    # Les valeurs par défaut sont utilisées si les variables globales ne sont pas encore initialisées
    safe_current_price = current_price if isinstance(current_price, (int, float, str)) else "N/A"
    safe_current_capital = current_capital if isinstance(current_capital, (int, float)) else 0.0
    safe_bot_status = bot_status if isinstance(bot_status, str) else "Inconnu"

    # Récupérer les trades les plus récents pour l'affichage
    # On combine la DB et la mémoire pour avoir une vue plus complète
    # La fonction get_trades() récupère déjà les dernières entrées DB
    # On s'assure que trade_history_memory est bien mise à jour et reflète les trades DB récents
    # Pour simplifier, on va juste utiliser les trades formatés de la DB pour le moment,
    # en supposant que trade_history_memory est synchronisé ou utilisé pour des logs très récents.
    # Une approche plus robuste serait de fusionner et dédupliquer ici si nécessaire.

    display_trades = []
    try:
        # Récupérer les trades de la base de données (les plus récents)
        db_trades = get_trades(limit=50) # Récupère les 50 derniers trades DB
        display_trades.extend(db_trades)

        # Ajouter les trades récents de la mémoire qui ne sont pas déjà dans db_trades
        # C'est utile si le bot a ajouté des trades très récemment avant la requête, mais qu'ils ne sont pas encore en DB
        # Ou si trade_history_memory contient des informations non persistées (ex: trades ouverts)
        # On va filtrer ceux qui ont un statut 'open' et qui ne sont pas déjà listés
        for mem_trade in trade_history_memory:
            if mem_trade not in display_trades and mem_trade.get('status') == 'open':
                display_trades.append(mem_trade)

        # Trier par timestamp pour un ordre cohérent (les plus récents en premier)
        # Assurez-vous que le timestamp est parsable
        display_trades.sort(key=lambda x: x.get('timestamp', '0'), reverse=True)

        # Limiter à 50 trades pour l'affichage final sur la page
        display_trades = display_trades[:50]

    except Exception as e:
        logger.error(f"Erreur lors de la récupération ou du formatage des trades pour le dashboard : {e}", exc_info=True)
        # En cas d'erreur, on affiche un message d'erreur dans le tableau
        display_trades = [{"error": "Erreur de chargement des trades"}]

    context = {
        "request": request,
        "current_price": safe_current_price,
        "current_capital": safe_current_capital,
        "bot_status": safe_bot_status,
        "trades_history": display_trades # 'display_trades' est une liste de dicts dont les valeurs sont des types simples.
    }
    logger.debug(f"Contexte pour le dashboard : Prix={context['current_price']}, Capital={context['current_capital']}, Status={context['bot_status']}, Nb Trades={len(context['trades_history'])}")

    try:
        return templates.TemplateResponse("index.html", context)
    except Exception as e:
        logger.error(f"Erreur lors du rendu du template 'index.html' (après tentative de formatage des trades) : {e}", exc_info=True)
        # Renvoyer une réponse d'erreur générique si le rendu échoue
        try:
            # Assurez-vous que le template error.html est simple et ne repose pas sur des structures complexes
            return templates.TemplateResponse("error.html", {"request": request, "error_message": "Erreur interne du serveur lors du chargement du tableau de bord."})
        except Exception as render_error:
            logger.error(f"Impossible de rendre même le template d'erreur : {render_error}", exc_info=True)
            return HTTPException(status_code=500, detail="Erreur serveur interne critique.")

@app.get("/api/stats")
async def api_stats():
    """API endpoint pour obtenir les statistiques actuelles."""
    global current_capital, bot_status, current_price, trade_history_memory

    # Récupérer les trades les plus récents
    trades = get_trades(limit=100) # Récupère plus de trades pour l'API
    # Ajouter les trades de mémoire qui sont ouverts et non persistés
    for mem_trade in trade_history_memory:
        if mem_trade not in trades and mem_trade.get('status') == 'open':
            trades.append(mem_trade)
    trades.sort(key=lambda x: x.get('timestamp', '0'), reverse=True)
    trades = trades[:100] # Limiter à 100 pour l'API

    return {
        "current_price": current_price,
        "current_capital": current_capital,
        "bot_status": bot_status,
        "trades_history": trades
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


# --- Points d'entrée pour le serveur ---

# Cette section est généralement utilisée pour le lancement local avec uvicorn
# Sur des plateformes comme Railway, le serveur est lancé différemment.
# Si vous déployez sur Railway, vous pouvez ignorer ce bloc.

# def run_local_server():
#     import uvicorn
#     logger.info("Lancement du serveur Uvicorn en mode développement...")
#     uvicorn.run(app, host="0.0.0.0", port=8080)

# if __name__ == "__main__":
#     # Initialiser la base de données au démarrage
#     initialize_database()
#     # Démarrer le serveur localement
#     run_local_server()
